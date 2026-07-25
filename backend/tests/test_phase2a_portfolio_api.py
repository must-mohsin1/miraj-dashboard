"""Phase 2A portfolio API contract tests.

These tests use local redacted fixtures and monkeypatched exchange clients only.
They must never perform live MEXC calls or read credentials.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from typing import Any, AsyncGenerator

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
from backend.models import ExchangeSyncState, FuturesAccountSnapshot, PositionHistory, User
from backend.tests.fixtures.phase2a_mexc import FUTURES_ACCOUNT_ASSETS

pytestmark = pytest.mark.anyio


def _coverage(stream: str, *, status: str = "fresh", complete: bool = True, reason: str | None = None) -> dict[str, Any]:
    now = datetime(2026, 7, 26, 2, 30, 0)
    return {
        "stream": stream,
        "status": status,
        "complete": complete,
        "reason": reason,
        "oldest_source_ts": now,
        "newest_source_ts": now,
        "rows_fetched_total": 1,
        "source_total": 1,
        "cursor": {"page_num": 1, "page_size": 100, "exhausted": True},
        "last_success_at": now if complete else None,
        "last_attempt_at": now,
        "error_code": None,
        "error_message": None,
        "unrecoverable_gaps": [],
    }


def _position(source_id: str | None = "redacted-pos-api-1") -> dict[str, Any]:
    return {
        "exchange_position_id": source_id,
        "symbol": "BTCUSDT",
        "side": "long",
        "size": 0.5,
        "entry_price": 60000.0,
        "exit_price": 61000.0,
        "pnl": 500.0,
        "pnl_percent": 1.6,
        "leverage": 5.0,
        "open_time": datetime(2026, 7, 25, 0, 0, 0),
        "close_time": datetime(2026, 7, 26, 0, 0, 0),
        "close_reason": "closed",
        "contract_size": 1.0,
        "reported_pnl": 500.0,
        "reported_roi_pct": 1.6,
        "source_state": "3",
        "source_updated_at": datetime(2026, 7, 26, 0, 0, 0),
    }


def _order(source_id: str = "redacted-order-api-1") -> dict[str, Any]:
    return {
        "exchange_order_id": source_id,
        "symbol": "BTCUSDT",
        "type": "limit",
        "side": "sell",
        "side_action": "Close Long",
        "price": 61000.0,
        "amount": 0.5,
        "filled": 0.5,
        "filled_price": 61000.0,
        "cost": 30500.0,
        "status": "filled",
        "timestamp": datetime(2026, 7, 26, 0, 0, 1),
        "fee": 1.2,
        "fee_currency": "USDT",
        "leverage": 5.0,
        "reduce_only": 1,
        "source_updated_at": datetime(2026, 7, 26, 0, 0, 1),
    }


def _portfolio_payload(*, partial: bool = False) -> dict[str, Any]:
    return {
        "balances": [],
        "positions": [],
        "trades": [],
        "position_history": [_position()],
        "order_history": [_order("redacted-order-api-1")],
        "futures_account": FUTURES_ACCOUNT_ASSETS["data"][0],
        "sync": {
            "positions_history": _coverage("positions_history"),
            "orders_history": _coverage("orders_history", status="partial" if partial else "fresh", complete=not partial, reason="exchange_boundary_before_source_total" if partial else None),
            "futures_account_assets": _coverage("futures_account_assets"),
        },
        "partial": partial,
    }


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="phase2a_portfolio_api_")
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


async def _create_user(username: str = "phase2api") -> tuple[User, str]:
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


async def _seed_phase2a_state(user_id: int, exchange: str = "mexc") -> None:
    from backend.services.phase2a_sync import persist_phase2a_sync_payload

    factory = database.get_session_factory()
    async with factory() as session:
        await persist_phase2a_sync_payload(
            session,
            user_id,
            exchange,
            _portfolio_payload(),
            datetime(2026, 7, 26, 2, 30, 0),
        )
        await session.commit()


async def test_refresh_response_adds_sync_futures_account_partial_and_persists_source_state(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from backend.routes import portfolio

    user, token = await _create_user("refreshapi")

    async def fake_get_exchange(**kwargs):
        return object()

    async def fake_fetch_portfolio(**kwargs):
        return _portfolio_payload(partial=True)

    monkeypatch.setattr(portfolio, "get_exchange", fake_get_exchange)
    monkeypatch.setattr(portfolio, "fetch_portfolio", fake_fetch_portfolio)

    resp = await client.post(
        "/api/v1/portfolio/mexc/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["exchange"] == "mexc"
    assert body["partial"] is True
    assert body["futures_account"]["settlement_asset"] == "USDT"
    assert body["futures_account"]["equity"] == 1234.56
    streams = {row["stream"]: row for row in body["sync"]}
    assert streams["orders_history"]["status"] == "partial"
    assert streams["funding"]["status"] == "not_enabled_phase_2b"
    assert streams["futures_transfers"]["supported_by_exchange"] is True
    assert streams["deposits"]["status"] == "unavailable"
    assert streams["withdrawals"]["reason"] == "requires_spot_wallet_endpoint_and_retention_probe_phase_2b"

    factory = database.get_session_factory()
    async with factory() as session:
        stored_position = await session.get(PositionHistory, 1)
        assert stored_position.exchange_position_id == "redacted-pos-api-1"
        assert stored_position.user_id == user.id


async def test_cached_portfolio_has_phase2a_contract_and_never_calls_exchange(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from backend.routes import portfolio

    user, token = await _create_user("cachedapi")
    await _seed_phase2a_state(user.id)

    async def fail_outbound(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("cached portfolio path attempted outbound exchange access")

    monkeypatch.setattr(portfolio, "get_exchange", fail_outbound)
    monkeypatch.setattr(portfolio, "fetch_portfolio", fail_outbound)
    monkeypatch.setattr(portfolio, "fetch_history", fail_outbound)

    resp = await client.get(
        "/api/v1/portfolio/mexc",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["position_history"][0]["exchange_position_id"] == "redacted-pos-api-1"
    assert body["order_history"][0]["exchange_order_id"] == "redacted-order-api-1"
    assert body["futures_account"]["available_balance"] == 1000.25
    assert body["partial"] is False
    streams = {row["stream"]: row for row in body["sync"]}
    assert set(streams) == {
        "positions_history",
        "orders_history",
        "futures_account_assets",
        "funding",
        "futures_transfers",
        "deposits",
        "withdrawals",
    }


async def test_live_history_response_includes_sync_partial_and_latest_futures_account(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from backend.routes import portfolio

    user, token = await _create_user("historyapi")
    await _seed_phase2a_state(user.id)

    async def fake_get_exchange(**kwargs):
        return object()

    async def fake_fetch_history(**kwargs):
        return {
            "position_history": [_position("redacted-pos-live-history")],
            "order_history": [_order("redacted-order-live-history")],
            "sync": {
                "positions_history": _coverage("positions_history"),
                "orders_history": _coverage("orders_history", status="partial", complete=False, reason="exchange_boundary_before_source_total"),
            },
            "partial": True,
        }

    monkeypatch.setattr(portfolio, "get_exchange", fake_get_exchange)
    monkeypatch.setattr(portfolio, "fetch_history", fake_fetch_history)

    resp = await client.get(
        "/api/v1/portfolio/mexc/history",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["partial"] is True
    assert body["futures_account"]["equity"] == 1234.56
    assert body["position_history"][0]["exchange_position_id"] == "redacted-pos-live-history"
    streams = {row["stream"]: row for row in body["sync"]}
    assert streams["orders_history"]["complete"] is False
    assert streams["orders_history"]["reason"] == "exchange_boundary_before_source_total"


async def test_sync_status_is_scoped_by_user_and_exchange_and_includes_phase2b_streams(
    app: FastAPI,
    client: AsyncClient,
):
    mexc_user, mexc_token = await _create_user("mexcowner")
    other_user, other_token = await _create_user("otherowner")
    await _seed_phase2a_state(mexc_user.id, "mexc")
    await _seed_phase2a_state(other_user.id, "binance")

    mexc_resp = await client.get(
        "/api/v1/portfolio/mexc/sync-status",
        headers={"Authorization": f"Bearer {mexc_token}"},
    )
    other_resp = await client.get(
        "/api/v1/portfolio/mexc/sync-status",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert mexc_resp.status_code == 200
    assert other_resp.status_code == 200
    mexc_streams = {row["stream"]: row for row in mexc_resp.json()["sync"]}
    other_streams = {row["stream"]: row for row in other_resp.json()["sync"]}
    assert mexc_streams["positions_history"]["status"] == "fresh"
    assert other_streams["positions_history"]["status"] == "stale"
    assert other_streams["funding"]["status"] == "not_enabled_phase_2b"
    assert other_streams["deposits"]["supported_by_exchange"] is False


async def test_legacy_pre_phase2a_rows_surface_unrecoverable_gap_without_inferred_position_id(
    app: FastAPI,
    client: AsyncClient,
):
    user, token = await _create_user("legacyapi")
    factory = database.get_session_factory()
    async with factory() as session:
        session.add(PositionHistory(user_id=user.id, exchange="mexc", **_position(source_id=None)))
        session.add(ExchangeSyncState(
            user_id=user.id,
            exchange="mexc",
            stream="positions_history",
            status="fresh",
            complete=True,
            rows_fetched_total=1,
            source_total=1,
            unrecoverable_gaps_json=[],
            last_success_at=datetime(2026, 7, 26, 2, 30, 0),
            last_attempt_at=datetime(2026, 7, 26, 2, 30, 0),
        ))
        await session.commit()

    resp = await client.get(
        "/api/v1/portfolio/mexc/sync-status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    streams = {row["stream"]: row for row in resp.json()["sync"]}
    gaps = streams["positions_history"]["unrecoverable_gaps"]
    assert gaps == [
        {
            "stream": "positions_history",
            "reason": "pre_phase_2a_missing_exchange_position_id",
            "position_history_id": 1,
            "symbol": "BTCUSDT",
            "close_time": "2026-07-26T00:00:00",
        }
    ]
    assert "exchange_position_id" not in gaps[0]
    assert "positionId" not in repr(gaps)
