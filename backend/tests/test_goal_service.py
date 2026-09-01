"""Month-scoped profit goal progress must use equity + flows, not closed PnL."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import (
    CapitalFlowLedger,
    ExchangeSyncState,
    FuturesAccountSnapshot,
    MonthlyProfitGoal,
    PositionHistory,
    User,
)
from backend.services.goal_service import (
    close_stale_goals,
    compute_month_progress,
    compute_period_analytics,
    month_bounds,
    snapshot_now,
    upsert_open_goal,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="goal_")
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
    user = User(username="goaluser", email="goal@test.local", hashed_password=hash_password("testpass123"))
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _sync(user_id: int, stream: str) -> ExchangeSyncState:
    return ExchangeSyncState(
        user_id=user_id,
        exchange="mexc",
        stream=stream,
        status="fresh",
        complete=True,
        rows_fetched_total=0,
        updated_at=datetime(2026, 8, 15),
    )


async def test_deposit_is_not_counted_as_profit(session: AsyncSession):
    user = await _user(session)
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(_sync(user.id, stream))
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=datetime(2026, 8, 2, 10, 0), synced_at=datetime(2026, 8, 2, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1300.0, source_ts=datetime(2026, 8, 20, 10, 0), synced_at=datetime(2026, 8, 20, 10, 0),
            ),
            CapitalFlowLedger(
                user_id=user.id, exchange="mexc", entry_type="deposit",
                exchange_entry_id="dep-1", asset="USDT", amount=200.0,
                signed_amount=200.0, occurred_at=datetime(2026, 8, 10, 12, 0),
                synced_at=datetime(2026, 8, 10, 12, 0),
            ),
            PositionHistory(
                user_id=user.id, exchange="mexc", symbol="BTC_USDT",
                side="long", size=1.0, entry_price=1.0, exit_price=2.0,
                pnl=9999.0, close_time=datetime(2026, 8, 12),
            ),
        ]
    )
    await session.flush()
    year, month, start, end = month_bounds(datetime(2026, 8, 21, tzinfo=timezone.utc))
    assert (year, month) == (2026, 8)
    progress = await compute_month_progress(session, user.id, "mexc", start_utc=start, end_utc=end)
    assert progress["available"] is True
    assert progress["net_profit"] == pytest.approx(100.0)
    assert progress["net_profit"] != 9999.0
    analytics = await compute_period_analytics(
        session, user.id, "mexc", start_utc=start, end_utc=end
    )
    assert analytics["available"] is True
    assert sum(row["net_profit"] for row in analytics["daily"]) == pytest.approx(100.0)
    assert analytics["monthly"][0]["net_external_flows"] == pytest.approx(200.0)


async def test_withdrawal_is_not_counted_as_trading_loss(session: AsyncSession):
    user = await _user(session)
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(_sync(user.id, stream))
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=datetime(2026, 8, 2, 10, 0),
                synced_at=datetime(2026, 8, 2, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=900.0, source_ts=datetime(2026, 8, 20, 10, 0),
                synced_at=datetime(2026, 8, 20, 10, 0),
            ),
            CapitalFlowLedger(
                user_id=user.id, exchange="mexc", entry_type="withdrawal",
                exchange_entry_id="withdrawal-1", asset="USDT", amount=200.0,
                signed_amount=-200.0, occurred_at=datetime(2026, 8, 10, 12, 0),
                synced_at=datetime(2026, 8, 10, 12, 0),
            ),
            PositionHistory(
                user_id=user.id, exchange="mexc", symbol="BTC_USDT",
                side="long", size=1.0, entry_price=2.0, exit_price=1.0,
                pnl=-9999.0, close_time=datetime(2026, 8, 12),
            ),
        ]
    )
    await session.flush()
    _, _, start, end = month_bounds(datetime(2026, 8, 21, tzinfo=timezone.utc))
    progress = await compute_month_progress(
        session, user.id, "mexc", start_utc=start, end_utc=end
    )
    assert progress["available"] is True
    assert progress["net_external_flows"] == pytest.approx(-200.0)
    assert progress["net_profit"] == pytest.approx(100.0)
    assert progress["net_profit"] != -9999.0


async def test_phase3_endpoints_skip_leading_zero_and_require_two_snapshots(
    session: AsyncSession,
):
    user = await _user(session)
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(_sync(user.id, stream))
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=0.0, source_ts=datetime(2026, 8, 1, 10, 0),
                synced_at=datetime(2026, 8, 1, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=datetime(2026, 8, 2, 10, 0),
                synced_at=datetime(2026, 8, 2, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1100.0, source_ts=datetime(2026, 8, 20, 10, 0),
                synced_at=datetime(2026, 8, 20, 10, 0),
            ),
        ]
    )
    await session.flush()
    _, _, august_start, august_end = month_bounds(
        datetime(2026, 8, 21, tzinfo=timezone.utc)
    )
    progress = await compute_month_progress(
        session, user.id, "mexc", start_utc=august_start, end_utc=august_end
    )
    analytics = await compute_period_analytics(
        session, user.id, "mexc", start_utc=august_start, end_utc=august_end
    )
    assert progress["available"] is True
    assert progress["opening_equity"] == pytest.approx(1000.0)
    assert progress["net_profit"] == pytest.approx(100.0)
    assert analytics["available"] is True
    assert analytics["daily"][0]["opening_equity"] == pytest.approx(1000.0)
    assert sum(row["net_profit"] for row in analytics["daily"]) == pytest.approx(100.0)

    session.add(
        FuturesAccountSnapshot(
            user_id=user.id, exchange="mexc", settlement_asset="USDT",
            equity=1200.0, source_ts=datetime(2026, 9, 2, 10, 0),
            synced_at=datetime(2026, 9, 2, 10, 0),
        )
    )
    await session.flush()
    _, _, september_start, september_end = month_bounds(
        datetime(2026, 9, 3, tzinfo=timezone.utc)
    )
    single = await compute_month_progress(
        session, user.id, "mexc", start_utc=september_start, end_utc=september_end
    )
    single_analytics = await compute_period_analytics(
        session, user.id, "mexc", start_utc=september_start, end_utc=september_end
    )
    assert single["available"] is False
    assert single["reason"] == "insufficient_equity_snapshots"
    assert single_analytics["available"] is False
    assert single_analytics["reason"] == "insufficient_equity_snapshots"


async def test_trailing_zero_equity_is_not_a_catastrophic_loss(session: AsyncSession):
    user = await _user(session)
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(_sync(user.id, stream))
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=datetime(2026, 8, 2, 10, 0),
                synced_at=datetime(2026, 8, 2, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1100.0, source_ts=datetime(2026, 8, 20, 10, 0),
                synced_at=datetime(2026, 8, 20, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=0.0, source_ts=datetime(2026, 8, 31, 10, 0),
                synced_at=datetime(2026, 8, 31, 10, 0),
            ),
        ]
    )
    await session.flush()
    _, _, start, end = month_bounds(datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc))
    progress = await compute_month_progress(
        session, user.id, "mexc", start_utc=start, end_utc=end
    )
    assert progress["available"] is True
    assert progress["ending_equity"] == pytest.approx(1100.0)
    assert progress["net_profit"] == pytest.approx(100.0)
    assert progress["return_pct"] == pytest.approx(10.0)


async def test_snapshot_reports_ahead_when_return_exceeds_goal(session: AsyncSession):
    user = await _user(session)
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(_sync(user.id, stream))
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=datetime(2026, 8, 2, 10, 0),
                synced_at=datetime(2026, 8, 2, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1120.0, source_ts=datetime(2026, 8, 20, 10, 0),
                synced_at=datetime(2026, 8, 20, 10, 0),
            ),
        ]
    )
    await session.flush()
    await upsert_open_goal(
        session, user.id, "mexc", target_return_pct=10.0, redeem_pct=40.0,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    result = await snapshot_now(
        session, user.id, now=datetime(2026, 8, 21, tzinfo=timezone.utc)
    )
    assert result["state"] == "AHEAD"
    assert result["progress"]["return_pct"] == pytest.approx(12.0)


async def test_month_bounds_uses_karachi_calendar_boundary():
    september = month_bounds(datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc))
    august = month_bounds(datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc))
    assert september[:2] == (2026, 9)
    assert august[:2] == (2026, 8)


async def test_snapshot_requires_an_open_goal_for_behind_state(session: AsyncSession):
    user = await _user(session)
    snap = await snapshot_now(session, user.id, now=datetime(2026, 8, 10, tzinfo=timezone.utc))
    assert snap["state"] == "NO_GOAL"
    await upsert_open_goal(
        session, user.id, "mexc",
        target_return_pct=35.0, redeem_pct=40.0,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    await session.flush()
    again = await snapshot_now(session, user.id, now=datetime(2026, 8, 10, tzinfo=timezone.utc))
    assert again["goal"]["target_return_pct"] == 35.0
    assert again["goal"]["redeem_pct"] == 40.0
    assert again["goal"]["reinvest_pct"] == 60.0


async def test_month_close_is_idempotent(session: AsyncSession):
    user = await _user(session)
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(_sync(user.id, stream))
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=datetime(2026, 8, 1, 10, 0),
                synced_at=datetime(2026, 8, 1, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1200.0, source_ts=datetime(2026, 8, 31, 10, 0),
                synced_at=datetime(2026, 8, 31, 10, 0),
            ),
        ]
    )
    await session.flush()
    goal = await upsert_open_goal(
        session,
        user.id,
        "mexc",
        target_return_pct=15.0,
        redeem_pct=25.0,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    first = await close_stale_goals(
        session, user.id, now=datetime(2026, 9, 2, tzinfo=timezone.utc)
    )
    assert [row.id for row in first] == [goal.id]
    saved = (
        goal.status,
        goal.closed_at,
        goal.closing_equity,
        goal.net_external_flows,
        goal.net_profit,
        goal.realized_return_pct,
        goal.declared_redeem_usd,
        goal.declared_reinvest_usd,
    )
    assert saved[0] == "closed"
    assert saved[2:] == pytest.approx((1200.0, 0.0, 200.0, 20.0, 50.0, 150.0))

    # Later equity must not rewrite an archived declaration.
    session.add(
        FuturesAccountSnapshot(
            user_id=user.id, exchange="mexc", settlement_asset="USDT",
            equity=1500.0, source_ts=datetime(2026, 8, 31, 12, 0),
            synced_at=datetime(2026, 8, 31, 12, 0),
        )
    )
    await session.flush()
    second = await close_stale_goals(
        session, user.id, now=datetime(2026, 9, 3, tzinfo=timezone.utc)
    )
    assert second == []
    assert (
        goal.status,
        goal.closed_at,
        goal.closing_equity,
        goal.net_external_flows,
        goal.net_profit,
        goal.realized_return_pct,
        goal.declared_redeem_usd,
        goal.declared_reinvest_usd,
    ) == saved


async def test_loss_month_declares_zero_redeem_and_reinvest(session: AsyncSession):
    user = await _user(session)
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(_sync(user.id, stream))
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=datetime(2026, 7, 2, 10, 0),
                synced_at=datetime(2026, 7, 2, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=850.0, source_ts=datetime(2026, 7, 30, 10, 0),
                synced_at=datetime(2026, 7, 30, 10, 0),
            ),
        ]
    )
    await session.flush()
    goal = await upsert_open_goal(
        session,
        user.id,
        "mexc",
        target_return_pct=10.0,
        redeem_pct=40.0,
        now=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    await close_stale_goals(
        session, user.id, now=datetime(2026, 8, 2, tzinfo=timezone.utc)
    )
    assert goal.status == "closed"
    assert goal.net_profit == pytest.approx(-150.0)
    assert goal.declared_redeem_usd == pytest.approx(0.0)
    assert goal.declared_reinvest_usd == pytest.approx(0.0)


async def test_close_fails_closed_when_capital_history_is_incomplete(session: AsyncSession):
    user = await _user(session)
    goal = MonthlyProfitGoal(
        user_id=user.id,
        exchange="mexc",
        period_year=2026,
        period_month=8,
        timezone="Asia/Karachi",
        target_return_pct=10.0,
        base_equity=1000.0,
        base_source="user_override",
        redeem_pct=40.0,
        reinvest_pct=60.0,
        status="open",
    )
    session.add(goal)
    await session.flush()
    closed = await close_stale_goals(
        session, user.id, now=datetime(2026, 9, 2, tzinfo=timezone.utc)
    )
    assert closed == []
    assert goal.status == "open"
    assert goal.net_profit is None
