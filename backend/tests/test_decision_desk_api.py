"""Integration coverage for the authenticated Decision Desk snapshot route."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend.auth import create_access_token, hash_password
from backend.database import Base, get_engine, get_session_factory, set_db_path
from backend.models import RealtimeSignal, User, WatchlistPair


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def app() -> FastAPI:
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="decision_desk_test_")
    os.close(fd)

    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(db_path)

    from backend.main import app as main_app

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield main_app

    await get_engine().dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client


@pytest.mark.anyio
async def test_now_returns_authenticated_user_watchlist_scope_and_persisted_signal_lifecycle(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from backend.routes import decision_desk

    async def fake_catalogue() -> set[str]:
        return {"BTC_USDT"}

    monkeypatch.setattr(decision_desk, "fetch_mexc_contract_catalogue", fake_catalogue)

    observed_at = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    factory = get_session_factory()
    async with factory() as session:
        user = User(username="desk-user", email="desk@example.com", hashed_password=hash_password("testpass123"))
        other_user = User(username="other-user", email="other@example.com", hashed_password=hash_password("testpass123"))
        session.add_all([user, other_user])
        await session.flush()
        session.add_all(
            [
                WatchlistPair(user_id=user.id, pair="BTC-USDT", sort_order=0),
                WatchlistPair(user_id=user.id, pair="ETH-USD", sort_order=1),
                RealtimeSignal(
                    user_id=user.id,
                    pair="BTCUSDT",
                    direction="LONG",
                    state="ACTIONABLE",
                    dedup_key="BTCUSDT:LONG:ACTIONABLE:1",
                    transition_count=1,
                    missing_gates="[]",
                    created_at=observed_at,
                    updated_at=observed_at,
                ),
                RealtimeSignal(
                    user_id=other_user.id,
                    pair="SOLUSDT",
                    direction="SHORT",
                    state="STALE",
                    dedup_key="SOLUSDT:SHORT:STALE:1",
                    transition_count=1,
                    missing_gates='["freshness"]',
                    created_at=observed_at,
                    updated_at=observed_at,
                ),
            ]
        )
        await session.commit()

    token = create_access_token(data={"sub": str(user.id)})
    response = await client.get("/api/v1/decision-desk/now", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated_at"]
    assert payload["watchlist"] == [
        {"pair": "BTC-USDT", "market_scope": "mexc_realtime", "mexc_symbol": "BTCUSDT"},
        {"pair": "ETH-USD", "market_scope": "research_only", "mexc_symbol": None},
    ]
    assert payload["signals"] == [
        {
            "pair": "BTCUSDT",
            "direction": "LONG",
            "state": "ACTIONABLE",
            "missing_gates": [],
            "created_at": "2026-07-17T12:00:00",
            "updated_at": "2026-07-17T12:00:00",
        }
    ]


@pytest.mark.anyio
async def test_now_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/decision-desk/now")

    assert response.status_code == 401
