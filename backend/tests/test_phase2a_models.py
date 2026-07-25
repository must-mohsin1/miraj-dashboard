"""Phase 2A MEXC schema model tests."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import ExchangeSyncState, FuturesAccountSnapshot, OrderHistory, PositionHistory, User
from backend.tests.fixtures.frozen_positions import (
    FROZEN_POSITIONS,
    FROZEN_REPORTED_TOTAL_PNL,
    expected_closed_position_totals,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="phase2a_models_")
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


async def _user(session, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _position(user_id: int, exchange: str, source_id: str | None = "pos-1") -> PositionHistory:
    return PositionHistory(
        user_id=user_id,
        exchange=exchange,
        exchange_position_id=source_id,
        symbol="BTC_USDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        exit_price=101.0,
        pnl=1.0,
        pnl_percent=1.0,
        reported_pnl=1.0,
        reported_roi_pct=1.0,
        source_state="closed",
        source_updated_at=datetime(2026, 7, 25, 12, 0),
        synced_at=datetime(2026, 7, 25, 12, 1),
        close_time=datetime(2026, 7, 25, 12, 0),
    )


def _order(user_id: int, exchange: str, source_id: str | None = "order-1") -> OrderHistory:
    return OrderHistory(
        user_id=user_id,
        exchange=exchange,
        exchange_order_id=source_id,
        symbol="BTC_USDT",
        type="limit",
        side="buy",
        price=100.0,
        amount=1.0,
        filled=1.0,
        cost=100.0,
        status="filled",
        timestamp=datetime(2026, 7, 25, 12, 0),
        source_updated_at=datetime(2026, 7, 25, 12, 0),
        synced_at=datetime(2026, 7, 25, 12, 1),
    )


async def test_phase2a_user_relationships_and_futures_account_snapshot(session):
    user = await _user(session, "phase2arel")
    snapshot = FuturesAccountSnapshot(
        user_id=user.id,
        exchange="mexc",
        settlement_asset="USDT",
        equity=1000.25,
        available_balance=900.0,
        frozen_balance=10.0,
        cash_balance=950.0,
        position_margin=50.0,
        unrealized_pnl=1.25,
        bonus=0.0,
        available_cash=925.0,
        debt_amount=0.0,
        source_ts=datetime(2026, 7, 25, 12, 0),
        synced_at=datetime(2026, 7, 25, 12, 1),
    )
    state = ExchangeSyncState(
        user_id=user.id,
        exchange="mexc",
        stream="futures_account_assets",
        status="fresh",
        cursor_json={"page_num": 1, "exhausted": True},
        rows_fetched_total=1,
        source_total=1,
        complete=True,
        unrecoverable_gaps_json=[],
        last_success_at=datetime(2026, 7, 25, 12, 1),
        last_attempt_at=datetime(2026, 7, 25, 12, 1),
        updated_at=datetime(2026, 7, 25, 12, 1),
    )
    session.add_all([snapshot, state])
    await session.flush()
    await session.refresh(user, attribute_names=["futures_account_snapshots", "exchange_sync_states"])

    assert user.futures_account_snapshots[0].settlement_asset == "USDT"
    assert user.futures_account_snapshots[0].equity == 1000.25
    assert user.exchange_sync_states[0].stream == "futures_account_assets"


async def test_exchange_sync_state_is_unique_per_user_exchange_stream(session):
    user = await _user(session, "phase2astate")
    other = await _user(session, "phase2aotherstate")
    timestamp = datetime(2026, 7, 25, 12, 0)
    session.add_all(
        [
            ExchangeSyncState(user_id=user.id, exchange="mexc", stream="positions_history", status="fresh", updated_at=timestamp),
            ExchangeSyncState(user_id=user.id, exchange="binance", stream="positions_history", status="fresh", updated_at=timestamp),
            ExchangeSyncState(user_id=other.id, exchange="mexc", stream="positions_history", status="fresh", updated_at=timestamp),
            ExchangeSyncState(user_id=user.id, exchange="mexc", stream="orders_history", status="error", updated_at=timestamp),
        ]
    )
    await session.flush()

    session.add(ExchangeSyncState(user_id=user.id, exchange="mexc", stream="positions_history", status="fresh", updated_at=timestamp))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_source_id_unique_indexes_are_partial_and_user_exchange_scoped(session):
    user = await _user(session, "phase2asource")
    other = await _user(session, "phase2aothersource")
    user_id = user.id
    other_id = other.id
    session.add_all(
        [
            _position(user_id, "mexc", "same-pos"),
            _position(user_id, "binance", "same-pos"),
            _position(other_id, "mexc", "same-pos"),
            _position(user_id, "mexc", None),
            _position(user_id, "mexc", None),
            _order(user_id, "mexc", "same-order"),
            _order(user_id, "binance", "same-order"),
            _order(other_id, "mexc", "same-order"),
            _order(user_id, "mexc", None),
            _order(user_id, "mexc", None),
        ]
    )
    await session.flush()
    await session.commit()

    session.add(_position(user_id, "mexc", "same-pos"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()

    session.add(_order(user_id, "mexc", "same-order"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_phase2a_indexes_exist_on_sqlite(session):
    position_indexes = (await session.execute(text("PRAGMA index_list('position_history')"))).fetchall()
    order_indexes = (await session.execute(text("PRAGMA index_list('order_history')"))).fetchall()
    sync_indexes = (await session.execute(text("PRAGMA index_list('exchange_sync_state')"))).fetchall()
    snapshot_indexes = (await session.execute(text("PRAGMA index_list('futures_account_snapshots')"))).fetchall()

    assert "uq_position_history_user_exchange_source_id" in {row[1] for row in position_indexes}
    assert "uq_order_history_user_exchange_source_id" in {row[1] for row in order_indexes}
    assert "ix_exchange_sync_state_user_exchange" in {row[1] for row in sync_indexes}
    assert "ix_futures_account_snapshots_user_exchange" in {row[1] for row in snapshot_indexes}


async def test_phase1_frozen_fixture_contract_is_preserved():
    expected = expected_closed_position_totals(FROZEN_POSITIONS)

    assert len(FROZEN_POSITIONS) == 49
    assert expected["winning_trades"] == 48
    assert expected["losing_trades"] == 1
    assert Decimal(str(FROZEN_REPORTED_TOTAL_PNL)) == Decimal("49.23")
