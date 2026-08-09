"""Trade Explorer full filtered CSV export."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import PositionHistory, User
from backend.services import analytics_service

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="trade_explorer_export_")
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


@pytest.fixture
async def user(session) -> User:
    user = User(
        username="exportcsv",
        email="exportcsv@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_positions(session, user_id: int) -> None:
    rows = [
        ("BTC_USDT", "long", 10.0, datetime(2026, 7, 24, 12, 0, 0)),
        ("ETH_USDT", "short", -5.0, datetime(2026, 7, 23, 12, 0, 0)),
        ("SOL_USDT", "long", 2.0, datetime(2026, 7, 22, 12, 0, 0)),
    ]
    for symbol, side, pnl, close_t in rows:
        session.add(
            PositionHistory(
                user_id=user_id,
                exchange="mexc",
                symbol=symbol,
                side=side,
                size=1.0,
                entry_price=100.0,
                exit_price=101.0 if pnl >= 0 else 99.0,
                pnl=pnl,
                pnl_percent=1.0,
                leverage=10,
                open_time=datetime(2026, 7, 20, 10, 0, 0),
                close_time=close_t,
                close_reason="manual",
            )
        )
    await session.commit()


async def test_export_all_filtered_rows_default_sort(session, user: User):
    await _seed_positions(session, user.id)
    payload = await analytics_service.export_trade_explorer_csv(
        session, user.id, "mexc"
    )
    assert payload["total_matched"] == 3
    assert payload["row_count"] == 3
    assert payload["truncated"] is False
    assert payload["csv"].startswith("\ufeff")
    assert "id,symbol,side" in payload["csv"]
    # Default sort -close_time → BTC first
    body = payload["csv"].lstrip("\ufeff")
    lines = [ln for ln in body.strip().split("\n") if ln]
    assert lines[0].startswith("id,symbol")
    assert "BTC_USDT" in lines[1]
    assert "ETH_USDT" in lines[2]
    assert "SOL_USDT" in lines[3]


async def test_export_respects_side_filter(session, user: User):
    await _seed_positions(session, user.id)
    payload = await analytics_service.export_trade_explorer_csv(
        session, user.id, "mexc", filters={"side": "long"}
    )
    assert payload["total_matched"] == 2
    assert payload["row_count"] == 2
    assert "ETH_USDT" not in payload["csv"]
    assert "BTC_USDT" in payload["csv"]
    assert "SOL_USDT" in payload["csv"]


async def test_export_truncates_at_max_rows(session, user: User):
    await _seed_positions(session, user.id)
    payload = await analytics_service.export_trade_explorer_csv(
        session, user.id, "mexc", max_rows=2
    )
    assert payload["total_matched"] == 3
    assert payload["row_count"] == 2
    assert payload["truncated"] is True
    assert payload["max_rows"] == 2


async def test_export_empty_filter_set(session, user: User):
    await _seed_positions(session, user.id)
    payload = await analytics_service.export_trade_explorer_csv(
        session, user.id, "mexc", filters={"symbols": ["NOPE_USDT"]}
    )
    assert payload["total_matched"] == 0
    assert payload["row_count"] == 0
    body = payload["csv"].lstrip("\ufeff").strip().split("\n")
    assert len(body) == 1  # header only
