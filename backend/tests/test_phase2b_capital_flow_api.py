"""Phase 2B capital-flow portfolio API tests.

Uses local fixtures and tmp SQLite only — no live exchange calls.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from typing import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import create_access_token, hash_password
from backend.database import Base, set_db_path
from backend.models import CapitalFlowLedger, ExchangeSyncState, User

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="phase2b_capital_flow_api_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def app(tmp_db_path: str, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(tmp_db_path)

    from backend.main import app as _app
    from backend.routes import portfolio

    monkeypatch.setattr(portfolio, "_require_supported_exchange", lambda exchange: exchange.strip().lower())

    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return _app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _create_user(username: str = "phase2bapi") -> tuple[User, str]:
    factory = database.get_session_factory()
    async with factory() as session:
        user = User(
            username=username,
            email=f"{username}@test.local",
            hashed_password=hash_password("testpass123"),
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        token = create_access_token(data={"sub": str(user.id)})
        await session.commit()
    return user, token


def _ledger_row(
    *,
    user_id: int,
    exchange: str = "mexc",
    entry_type: str = "funding",
    exchange_entry_id: str = "entry-1",
    asset: str = "USDT",
    amount: float = 1.5,
    signed_amount: float = -1.5,
    occurred_at: datetime | None = None,
    synced_at: datetime | None = None,
) -> CapitalFlowLedger:
    return CapitalFlowLedger(
        user_id=user_id,
        exchange=exchange,
        entry_type=entry_type,
        exchange_entry_id=exchange_entry_id,
        asset=asset,
        amount=amount,
        signed_amount=signed_amount,
        status="paid",
        occurred_at=occurred_at,
        source_updated_at=occurred_at,
        synced_at=synced_at or datetime(2026, 8, 4, 12, 0, 0),
    )


def _sync_state(
    *,
    user_id: int,
    stream: str,
    status: str = "fresh",
    complete: bool = True,
    reason: str | None = None,
    exchange: str = "mexc",
) -> ExchangeSyncState:
    now = datetime(2026, 8, 4, 12, 0, 0)
    return ExchangeSyncState(
        user_id=user_id,
        exchange=exchange,
        stream=stream,
        status=status,
        complete=complete,
        partial_reason=reason,
        rows_fetched_total=1 if complete or status == "partial" else 0,
        source_total=1,
        last_success_at=now if complete else None,
        last_attempt_at=now,
    )


async def test_capital_flow_endpoint_returns_sorted_entries_and_coverage(
    app: FastAPI,
    client: AsyncClient,
):
    user, token = await _create_user("capitalowner")
    other, _ = await _create_user("othercapital")

    older = datetime(2026, 8, 1, 10, 0, 0)
    newer = datetime(2026, 8, 3, 15, 30, 0)
    mid = datetime(2026, 8, 2, 12, 0, 0)

    factory = database.get_session_factory()
    async with factory() as session:
        session.add_all([
            _ledger_row(
                user_id=user.id,
                exchange_entry_id="older-funding",
                occurred_at=older,
                amount=0.5,
                signed_amount=-0.5,
            ),
            _ledger_row(
                user_id=user.id,
                exchange_entry_id="newer-deposit",
                entry_type="deposit",
                occurred_at=newer,
                amount=100.0,
                signed_amount=100.0,
            ),
            _ledger_row(
                user_id=user.id,
                exchange_entry_id="mid-transfer",
                entry_type="futures_transfer",
                occurred_at=mid,
                amount=25.0,
                signed_amount=-25.0,
            ),
            # Other user's row must not leak
            _ledger_row(
                user_id=other.id,
                exchange_entry_id="other-user-entry",
                occurred_at=datetime(2026, 8, 4, 0, 0, 0),
                amount=999.0,
                signed_amount=999.0,
            ),
            _sync_state(
                user_id=user.id,
                stream="funding",
                status="partial",
                complete=False,
                reason="exchange_boundary_before_source_total",
            ),
            _sync_state(
                user_id=user.id,
                stream="deposits",
                status="fresh",
                complete=True,
            ),
        ])
        await session.commit()

    resp = await client.get(
        "/api/v1/portfolio/mexc/capital-flow",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["exchange"] == "mexc"
    assert body["limit"] == 200
    assert body["offset"] == 0
    assert len(body["entries"]) == 3
    assert all(e["exchange_entry_id"] != "other-user-entry" for e in body["entries"])

    times = [e["occurred_at"] for e in body["entries"]]
    assert times == sorted(times, reverse=True)
    assert body["entries"][0]["exchange_entry_id"] == "newer-deposit"
    assert body["entries"][0]["entry_type"] == "deposit"
    assert body["entries"][0]["signed_amount"] == 100.0

    streams = {s["stream"]: s for s in body["sync"]}
    assert set(streams) == {"funding", "futures_transfers", "deposits", "withdrawals"}
    assert streams["funding"]["status"] == "partial"
    assert streams["deposits"]["status"] == "fresh"
    # Missing streams use generic stale/no_sync_state defaults
    assert streams["futures_transfers"]["status"] == "stale"
    assert streams["futures_transfers"]["reason"] == "no_sync_state"
    assert streams["withdrawals"]["status"] == "stale"
    assert "not_enabled_phase_2b" not in {s["status"] for s in body["sync"]}
    # Funding is meaningfully partial → partial true (stale placeholders alone would not)
    assert body["partial"] is True


async def test_capital_flow_partial_false_for_pure_no_sync_state_defaults(
    app: FastAPI,
    client: AsyncClient,
):
    """Pre-sync stale/no_sync_state placeholders must not flip partial=true."""
    user, token = await _create_user("presyncflow")

    resp = await client.get(
        "/api/v1/portfolio/mexc/capital-flow",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    streams = {s["stream"]: s for s in body["sync"]}
    assert set(streams) == {"funding", "futures_transfers", "deposits", "withdrawals"}
    for stream in streams.values():
        assert stream["status"] == "stale"
        assert stream["reason"] == "no_sync_state"
        assert stream["complete"] is False
    assert body["partial"] is False
    assert body["entries"] == []


async def test_capital_flow_partial_true_for_unavailable_or_error(
    app: FastAPI,
    client: AsyncClient,
):
    user, token = await _create_user("gapflow")

    factory = database.get_session_factory()
    async with factory() as session:
        session.add_all([
            _sync_state(
                user_id=user.id,
                stream="funding",
                status="unavailable",
                complete=False,
                reason="stream_not_supported",
            ),
            _sync_state(
                user_id=user.id,
                stream="deposits",
                status="error",
                complete=False,
                reason="rate_limit",
            ),
        ])
        await session.commit()

    resp = await client.get(
        "/api/v1/portfolio/mexc/capital-flow",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    streams = {s["stream"]: s for s in body["sync"]}
    assert streams["funding"]["status"] == "unavailable"
    assert streams["deposits"]["status"] == "error"
    assert body["partial"] is True


async def test_capital_flow_is_user_scoped(
    app: FastAPI,
    client: AsyncClient,
):
    user_a, token_a = await _create_user("usera_flow")
    user_b, token_b = await _create_user("userb_flow")

    factory = database.get_session_factory()
    async with factory() as session:
        session.add_all([
            _ledger_row(
                user_id=user_a.id,
                exchange_entry_id="a-only",
                occurred_at=datetime(2026, 8, 1, 0, 0, 0),
            ),
            _ledger_row(
                user_id=user_b.id,
                exchange_entry_id="b-only",
                occurred_at=datetime(2026, 8, 2, 0, 0, 0),
                amount=50.0,
                signed_amount=50.0,
            ),
            _sync_state(user_id=user_a.id, stream="funding", status="fresh", complete=True),
            _sync_state(user_id=user_b.id, stream="funding", status="fresh", complete=True),
        ])
        await session.commit()

    resp_a = await client.get(
        "/api/v1/portfolio/mexc/capital-flow",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resp_b = await client.get(
        "/api/v1/portfolio/mexc/capital-flow",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    ids_a = {e["exchange_entry_id"] for e in resp_a.json()["entries"]}
    ids_b = {e["exchange_entry_id"] for e in resp_b.json()["entries"]}
    assert ids_a == {"a-only"}
    assert ids_b == {"b-only"}


async def test_cached_portfolio_no_longer_emits_phase2b_placeholder(
    app: FastAPI,
    client: AsyncClient,
):
    """Without capital sync state, defaults are stale/no_sync_state not not_enabled_phase_2b."""
    user, token = await _create_user("nocapitalstate")

    resp = await client.get(
        "/api/v1/portfolio/mexc",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    streams = {row["stream"]: row for row in body["sync"]}
    for stream in ("funding", "futures_transfers", "deposits", "withdrawals"):
        assert streams[stream]["status"] == "stale"
        assert streams[stream]["reason"] == "no_sync_state"
        assert streams[stream]["status"] != "not_enabled_phase_2b"
        assert streams[stream]["reason"] != "not_enabled_phase_2b"
        assert streams[stream]["reason"] != "requires_spot_wallet_endpoint_and_retention_probe_phase_2b"


async def test_capital_flow_pagination_limit_and_offset(
    app: FastAPI,
    client: AsyncClient,
):
    user, token = await _create_user("paginateflow")

    factory = database.get_session_factory()
    async with factory() as session:
        for i in range(5):
            session.add(
                _ledger_row(
                    user_id=user.id,
                    exchange_entry_id=f"page-{i}",
                    occurred_at=datetime(2026, 8, 1 + i, 0, 0, 0),
                    amount=float(i),
                    signed_amount=float(i),
                )
            )
        await session.commit()

    resp = await client.get(
        "/api/v1/portfolio/mexc/capital-flow?limit=2&offset=1",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["entries"]) == 2
    # Desc by occurred_at: page-4, page-3, page-2, page-1, page-0 → offset 1 → page-3, page-2
    assert [e["exchange_entry_id"] for e in body["entries"]] == ["page-3", "page-2"]
