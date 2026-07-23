"""Timezone and period grouping tests for Portfolio Intelligence Phase 0."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

import pytest
from fastapi import HTTPException

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import PositionHistory, User
from backend.routes import analytics as analytics_routes
from backend.services import analytics_service

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="portfolio_period_phase0_")
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
        username="periodanalytics",
        email="periodanalytics@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _closed_position(user: User, *, close_time: datetime, pnl: float, symbol: str = "BTC_USDT") -> PositionHistory:
    return PositionHistory(
        user_id=user.id,
        exchange="mexc",
        symbol=symbol,
        side="long",
        size=1.0,
        entry_price=100.0,
        exit_price=101.0,
        pnl=pnl,
        pnl_percent=1.0,
        leverage=5.0,
        open_time=datetime(2026, 7, 23, 20, 0),
        close_time=close_time,
        close_reason="unknown",
    )


async def test_daily_pnl_groups_by_requested_timezone_rollover(session, user: User):
    session.add(_closed_position(user, close_time=datetime(2026, 7, 23, 23, 30), pnl=12.34))
    await session.flush()

    utc_days = await analytics_service.get_daily_pnl(session, user.id, "mexc", timezone_name="UTC")
    karachi_days = await analytics_service.get_daily_pnl(session, user.id, "mexc", timezone_name="Asia/Karachi")

    assert utc_days["timezone"] == "UTC"
    assert utc_days["days"] == [{"date": "2026-07-23", "pnl": 12.34}]
    assert karachi_days["timezone"] == "Asia/Karachi"
    assert karachi_days["days"] == [{"date": "2026-07-24", "pnl": 12.34}]


async def test_daily_pnl_from_to_filter_returns_empty_period(session, user: User):
    session.add(_closed_position(user, close_time=datetime(2026, 7, 23, 23, 30), pnl=12.34))
    await session.flush()

    days = await analytics_service.get_daily_pnl(
        session,
        user.id,
        "mexc",
        timezone_name="UTC",
        from_ts=datetime(2026, 7, 24, 0, 0),
        to_ts=datetime(2026, 7, 25, 0, 0),
    )

    assert days["exchange"] == "mexc"
    assert days["timezone"] == "UTC"
    assert days["period"] == {"from": "2026-07-24T00:00:00+00:00", "to": "2026-07-25T00:00:00+00:00"}
    assert days["days"] == []


async def test_daily_pnl_week_rollover_uses_iso_week_across_year_boundary(session, user: User):
    session.add_all(
        [
            _closed_position(user, close_time=datetime(2026, 12, 31, 23, 30), pnl=5.0, symbol="BTC_USDT"),
            _closed_position(user, close_time=datetime(2027, 1, 1, 0, 30), pnl=7.0, symbol="ETH_USDT"),
        ]
    )
    await session.flush()

    grouped = await analytics_service.get_period_pnl(session, user.id, "mexc", timezone_name="UTC", group_by="week")

    assert grouped["timezone"] == "UTC"
    assert grouped["group_by"] == "week"
    assert grouped["periods"] == [{"period": "2026-W53", "pnl": 12.0}]


async def test_daily_pnl_route_rejects_invalid_timezone(session, user: User, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analytics_routes, "_require_supported_exchange", lambda exchange: exchange.lower())

    with pytest.raises(HTTPException) as exc:
        await analytics_routes.get_daily_pnl(
            "mexc",
            timezone_name="Not/AZone",
            current_user=user,
            session=session,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid timezone: Not/AZone"
