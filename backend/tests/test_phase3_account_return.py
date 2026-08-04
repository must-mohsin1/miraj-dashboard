"""Phase 3 cash-flow-adjusted account return tests."""

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
from backend.models import (
    CapitalFlowLedger,
    ExchangeSyncState,
    FuturesAccountSnapshot,
    PositionHistory,
    User,
)
from backend.services import analytics_service
from backend.services.phase3_account_return import compute_account_return

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="phase3_return_")
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


async def _user(session: AsyncSession, username: str = "phase3ret") -> User:
    user = User(
        username=username,
        email=f"{username}@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _sync(
    user_id: int,
    stream: str,
    *,
    status: str = "fresh",
    complete: bool = True,
    reason: str | None = None,
) -> ExchangeSyncState:
    return ExchangeSyncState(
        user_id=user_id,
        exchange="mexc",
        stream=stream,
        status=status,
        complete=complete,
        partial_reason=reason,
        rows_fetched_total=0,
        updated_at=datetime(2026, 8, 4, 12, 0, 0),
    )


def _snap(
    user_id: int,
    equity: float,
    source_ts: datetime,
    settlement_asset: str = "USDT",
) -> FuturesAccountSnapshot:
    return FuturesAccountSnapshot(
        user_id=user_id,
        exchange="mexc",
        settlement_asset=settlement_asset,
        equity=equity,
        source_ts=source_ts,
        synced_at=source_ts,
    )


def _flow(
    user_id: int,
    entry_type: str,
    signed: float,
    occurred: datetime,
    exchange_entry_id: str,
) -> CapitalFlowLedger:
    return CapitalFlowLedger(
        user_id=user_id,
        exchange="mexc",
        entry_type=entry_type,
        exchange_entry_id=exchange_entry_id,
        asset="USDT",
        amount=abs(signed),
        signed_amount=signed,
        occurred_at=occurred,
        synced_at=occurred,
    )


async def test_account_return_formula_with_deposit(session: AsyncSession):
    user = await _user(session)
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t1 = datetime(2026, 7, 15, 0, 0, 0)
    t_end = datetime(2026, 8, 1, 0, 0, 0)
    # Opening 1000, deposit +100 mid-period, ending 1200
    # net_external = 100
    # profit = 1200 - 1000 - 100 = 100
    # return = (1200 - 100) / 1000 - 1 = 0.1 → 10%
    session.add_all(
        [
            _snap(user.id, 1000.0, t0),
            _snap(user.id, 1200.0, t_end),
            _flow(user.id, "deposit", 100.0, t1, "dep-1"),
            _sync(user.id, "deposits"),
            _sync(user.id, "withdrawals"),
            _sync(user.id, "futures_transfers"),
        ]
    )
    await session.flush()

    result = await compute_account_return(session, user.id, "mexc")

    assert result["account_return_pct"] == 10.0
    assert result["net_account_profit_usd"] == 100.0
    assert result["opening_equity"] == 1000.0
    assert result["ending_equity"] == 1200.0
    assert result["net_external_flows"] == 100.0
    assert result["complete"] is True
    assert result["reason"] is None


async def test_funding_is_not_counted_as_external_flow(session: AsyncSession):
    user = await _user(session, "phase3fund")
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t_mid = datetime(2026, 7, 10, 0, 0, 0)
    t_end = datetime(2026, 8, 1, 0, 0, 0)
    session.add_all(
        [
            _snap(user.id, 1000.0, t0),
            _snap(user.id, 1050.0, t_end),
            _flow(user.id, "funding", -5.0, t_mid, "fund-1"),
            _sync(user.id, "deposits"),
            _sync(user.id, "withdrawals"),
            _sync(user.id, "futures_transfers"),
        ]
    )
    await session.flush()

    result = await compute_account_return(session, user.id, "mexc")

    assert result["net_external_flows"] == 0.0
    assert result["net_account_profit_usd"] == 50.0
    assert result["account_return_pct"] == 5.0


async def test_incomplete_deposits_blocks_return(session: AsyncSession):
    user = await _user(session, "phase3inc")
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t_end = datetime(2026, 8, 1, 0, 0, 0)
    session.add_all(
        [
            _snap(user.id, 1000.0, t0),
            _snap(user.id, 1100.0, t_end),
            _sync(user.id, "deposits", status="partial", complete=False, reason="exchange_boundary"),
            _sync(user.id, "withdrawals"),
            _sync(user.id, "futures_transfers"),
        ]
    )
    await session.flush()

    result = await compute_account_return(session, user.id, "mexc")

    assert result["account_return_pct"] is None
    assert result["account_return_pct_reason"] == "capital_history_incomplete"
    assert result["complete"] is False


async def test_unavailable_stream_is_treated_as_empty_complete(session: AsyncSession):
    user = await _user(session, "phase3unav")
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t_end = datetime(2026, 8, 1, 0, 0, 0)
    session.add_all(
        [
            _snap(user.id, 500.0, t0),
            _snap(user.id, 550.0, t_end),
            _sync(user.id, "deposits", status="unavailable", complete=False),
            _sync(user.id, "withdrawals", status="unavailable", complete=False),
            _sync(user.id, "futures_transfers"),
        ]
    )
    await session.flush()

    result = await compute_account_return(session, user.id, "mexc")

    assert result["account_return_pct"] == 10.0
    assert result["net_external_flows"] == 0.0


async def test_missing_sync_state_is_capital_history_missing(session: AsyncSession):
    user = await _user(session, "phase3miss")
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t_end = datetime(2026, 8, 1, 0, 0, 0)
    session.add_all([_snap(user.id, 100.0, t0), _snap(user.id, 110.0, t_end)])
    await session.flush()

    result = await compute_account_return(session, user.id, "mexc")

    assert result["account_return_pct"] is None
    assert result["account_return_pct_reason"] == "capital_history_missing"


async def test_flat_futures_equity_is_futures_equity_flat_not_spot_base(session: AsyncSession):
    """Zero futures equity fails closed — never falls back to spot as return base."""
    user = await _user(session, "phase3flat")
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t_end = datetime(2026, 8, 1, 0, 0, 0)
    session.add_all(
        [
            _snap(user.id, 0.0, t0, "USDT"),
            _snap(user.id, 0.0, t_end, "USDT"),
            _sync(user.id, "deposits"),
            _sync(user.id, "withdrawals"),
            _sync(user.id, "futures_transfers"),
        ]
    )
    await session.flush()

    result = await compute_account_return(session, user.id, "mexc")

    assert result["account_return_pct"] is None
    assert result["account_return_pct_reason"] == "futures_equity_flat"
    assert result["opening_equity"] == 0.0
    assert result["ending_equity"] == 0.0
    assert result["complete"] is False
    # Basis stays unset when unavailable — product rule is futures-only.
    assert result["basis"] is None


def test_select_primary_futures_prefers_usdt_over_dust_steth():
    from backend.services.futures_settlement import select_primary_futures_raw

    raw = select_primary_futures_raw(
        [
            {"currency": "STETH", "equity": "0"},
            {"currency": "SHIB", "equity": "0"},
            {"currency": "USDT", "equity": "1234.5"},
            {"currency": "BTC", "equity": "0.01"},
        ]
    )
    assert raw is not None
    assert raw["currency"] == "USDT"


def test_select_primary_futures_prefers_nonzero_over_zero_usdt():
    from backend.services.futures_settlement import select_primary_futures_raw

    # If USDT is empty but another asset has equity, prefer non-zero.
    raw = select_primary_futures_raw(
        [
            {"currency": "USDT", "equity": "0"},
            {"currency": "BTC", "equity": "2.5"},
        ]
    )
    assert raw is not None
    assert raw["currency"] == "BTC"


async def test_account_return_ignores_zero_steth_prefers_usdt_series(session: AsyncSession):
    user = await _user(session, "phase3sett")
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t1 = datetime(2026, 7, 10, 0, 0, 0)
    t_end = datetime(2026, 8, 1, 0, 0, 0)
    session.add_all(
        [
            # Dust series first chronologically — must not win.
            _snap(user.id, 0.0, t0, "STETH"),
            _snap(user.id, 0.0, t_end, "STETH"),
            _snap(user.id, 1000.0, t0, "USDT"),
            _snap(user.id, 1100.0, t_end, "USDT"),
            _flow(user.id, "futures_transfer", 0.0, t1, "xfer-z"),  # no-op flow
            _sync(user.id, "deposits"),
            _sync(user.id, "withdrawals"),
            _sync(user.id, "futures_transfers"),
        ]
    )
    await session.flush()

    result = await compute_account_return(session, user.id, "mexc")

    assert result["settlement_asset"] == "USDT"
    assert result["account_return_pct"] == 10.0
    assert result["opening_equity"] == 1000.0
    assert result["ending_equity"] == 1100.0


async def test_performance_metrics_merges_account_return(session: AsyncSession):
    user = await _user(session, "phase3perf")
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t_end = datetime(2026, 8, 1, 0, 0, 0)
    session.add_all(
        [
            _snap(user.id, 1000.0, t0),
            _snap(user.id, 1100.0, t_end),
            _sync(user.id, "deposits"),
            _sync(user.id, "withdrawals"),
            _sync(user.id, "futures_transfers"),
            PositionHistory(
                user_id=user.id,
                exchange="mexc",
                symbol="BTCUSDT",
                side="long",
                size=1.0,
                entry_price=100.0,
                exit_price=110.0,
                pnl=25.0,
                pnl_percent=10.0,
                leverage=5.0,
                close_time=t_end,
            ),
        ]
    )
    await session.flush()

    metrics = await analytics_service.compute_performance_metrics(session, user.id, "mexc")

    assert metrics["total_pnl"] == 25.0
    assert metrics["total_pnl_percent"] is None
    assert metrics["account_return_pct"] == 10.0
    assert metrics["account_return_pct_reason"] is None
    assert metrics["net_account_profit_usd"] == 100.0
    assert metrics["unavailable_reason"] is None
    assert metrics["complete"] is True
