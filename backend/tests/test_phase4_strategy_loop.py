"""Phase 4 strategy loop: journal filters, auto-link, concentration insights."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from typing import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import create_access_token, hash_password
from backend.database import Base, set_db_path
from backend.models import PositionHistory, TradeJournalEntry, User
from backend.services import analytics_service

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="phase4_loop_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def app(tmp_db_path: str) -> FastAPI:
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(tmp_db_path)
    from backend.main import app as _app

    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return _app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def session(tmp_db_path: str):
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(tmp_db_path)
    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = database.get_session_factory()
    async with factory() as s:
        yield s


async def _create_user(username: str = "p4user") -> tuple[User, str]:
    factory = database.get_session_factory()
    async with factory() as s:
        user = User(
            username=username,
            email=f"{username}@test.local",
            hashed_password=hash_password("testpass123"),
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        token = create_access_token(data={"sub": str(user.id)})
        return user, token


async def test_list_journal_filters_by_tag_and_untagged(client: AsyncClient, app: FastAPI):
    user, token = await _create_user("p4tag")
    factory = database.get_session_factory()
    async with factory() as s:
        s.add_all(
            [
                TradeJournalEntry(
                    user_id=user.id, exchange="mexc", symbol="BTCUSDT", tags="scalp", pnl=1.0
                ),
                TradeJournalEntry(
                    user_id=user.id,
                    exchange="mexc",
                    symbol="ETHUSDT",
                    tags="scalp,swing",
                    pnl=2.0,
                ),
                TradeJournalEntry(
                    user_id=user.id, exchange="mexc", symbol="SOLUSDT", tags=None, pnl=3.0
                ),
            ]
        )
        await s.commit()

    headers = {"Authorization": f"Bearer {token}"}
    scalp = await client.get("/api/v1/journal", params={"tag": "scalp"}, headers=headers)
    assert scalp.status_code == 200
    body = scalp.json()
    assert body["total"] == 2
    assert {e["symbol"] for e in body["entries"]} == {"BTCUSDT", "ETHUSDT"}

    untagged = await client.get("/api/v1/journal", params={"tag": "untagged"}, headers=headers)
    assert untagged.status_code == 200
    assert untagged.json()["total"] == 1
    assert untagged.json()["entries"][0]["symbol"] == "SOLUSDT"


async def test_create_journal_auto_links_newest_unlinked_position(client: AsyncClient, app: FastAPI):
    user, token = await _create_user("p4link")
    factory = database.get_session_factory()
    async with factory() as s:
        older = PositionHistory(
            user_id=user.id,
            exchange="mexc",
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            exit_price=105.0,
            pnl=5.0,
            close_time=datetime(2026, 7, 1, 12, 0, 0),
        )
        newer = PositionHistory(
            user_id=user.id,
            exchange="mexc",
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=110.0,
            exit_price=120.0,
            pnl=10.0,
            close_time=datetime(2026, 8, 1, 12, 0, 0),
        )
        s.add_all([older, newer])
        await s.commit()
        await s.refresh(newer)
        newer_id = newer.id

    res = await client.post(
        "/api/v1/journal",
        headers={"Authorization": f"Bearer {token}"},
        json={"symbol": "BTCUSDT", "exchange": "mexc", "tags": "breakout"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["position_id"] == newer_id
    assert body["pnl"] == 10.0
    assert body["entry_price"] == 110.0


async def test_journal_summary_includes_symbol_concentration(session: AsyncSession):
    user = User(
        username="p4conc",
        email="p4conc@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    for i in range(4):
        session.add(
            PositionHistory(
                user_id=user.id,
                exchange="mexc",
                symbol="BTCUSDT" if i < 3 else "ETHUSDT",
                side="long",
                size=1.0,
                entry_price=1.0,
                exit_price=2.0,
                pnl=10.0 if i < 3 else 1.0,
                close_time=datetime(2026, 8, 1, i, 0, 0),
            )
        )
    session.add(
        TradeJournalEntry(
            user_id=user.id, exchange="mexc", symbol="BTCUSDT", tags="scalp", pnl=10.0
        )
    )
    await session.flush()

    summary = await analytics_service.get_journal_summary(session, user.id, "mexc")
    ids = {i["id"] for i in summary["insights"]}
    assert "symbol_pnl_concentration" in ids
    conc = next(i for i in summary["insights"] if i["id"] == "symbol_pnl_concentration")
    assert conc["evidence_symbol"] == "BTCUSDT"
    assert conc.get("evidence_href")
