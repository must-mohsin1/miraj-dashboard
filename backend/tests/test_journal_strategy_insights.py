"""Phase 4 journal tag scorecards + strategy insights."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import PositionHistory, TradeJournalEntry, User
from backend.services import analytics_service

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="journal_strategy_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


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


async def _user(session: AsyncSession) -> User:
    user = User(
        username="strat1",
        email="strat1@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def test_journal_summary_empty_yields_no_entries_insight(session: AsyncSession):
    user = await _user(session)
    summary = await analytics_service.get_journal_summary(session, user.id, "mexc")
    assert summary["total_entries"] == 0
    assert summary["linked_to_position"] == 0
    assert summary["insights"][0]["id"] == "no_journal_entries"


async def test_journal_summary_tags_avg_and_insights(session: AsyncSession):
    user = await _user(session)
    pos = PositionHistory(
        user_id=user.id,
        exchange="mexc",
        symbol="BTCUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        exit_price=110.0,
        pnl=25.0,
        close_time=datetime(2026, 8, 1, 12, 0, 0),
    )
    session.add(pos)
    await session.flush()

    session.add_all(
        [
            TradeJournalEntry(
                user_id=user.id,
                exchange="mexc",
                symbol="BTCUSDT",
                position_id=pos.id,
                tags="scalp,breakout",
                pnl=25.0,
            ),
            TradeJournalEntry(
                user_id=user.id,
                exchange="mexc",
                symbol="ETHUSDT",
                tags="scalp",
                pnl=10.0,
            ),
            TradeJournalEntry(
                user_id=user.id,
                exchange="mexc",
                symbol="SOLUSDT",
                tags="fomo",
                pnl=-15.0,
            ),
            TradeJournalEntry(
                user_id=user.id,
                exchange="mexc",
                symbol="XRPUSDT",
                tags="fomo",
                pnl=-5.0,
            ),
            TradeJournalEntry(
                user_id=user.id,
                exchange="mexc",
                symbol="DOGEUSDT",
                tags=None,
                pnl=1.0,
            ),
        ]
    )
    await session.flush()

    summary = await analytics_service.get_journal_summary(session, user.id, "mexc")
    assert summary["total_entries"] == 5
    assert summary["linked_to_position"] == 1
    assert summary["tags"]["scalp"]["trade_count"] == 2
    assert summary["tags"]["scalp"]["total_pnl"] == 35.0
    assert summary["tags"]["scalp"]["avg_pnl"] == 17.5
    assert summary["tags"]["fomo"]["total_pnl"] == -20.0

    insight_ids = {i["id"] for i in summary["insights"]}
    assert "best_tag_edge" in insight_ids
    assert "worst_tag_drag" in insight_ids
    assert "position_journal_link_rate" in insight_ids
