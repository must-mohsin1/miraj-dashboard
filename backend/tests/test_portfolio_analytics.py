"""Focused Portfolio Intelligence Phase 0 analytics correctness tests."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import PortfolioBalance, PortfolioPosition, PortfolioSnapshot, PositionHistory, User
from backend.routes import analytics as analytics_routes
from backend.services import analytics_service
from backend.tests.fixtures.frozen_positions import (
    FROZEN_LOSS_COUNT,
    FROZEN_POSITIONS,
    FROZEN_REPORTED_TOTAL_PNL,
    FROZEN_WIN_COUNT,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="portfolio_analytics_phase0_")
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
        username="portfolioanalytics",
        email="portfolioanalytics@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc).replace(tzinfo=None)


def _position(user: User, exchange: str = "mexc", **overrides) -> PositionHistory:
    data = {
        "user_id": user.id,
        "exchange": exchange,
        "symbol": "BTC_USDT",
        "side": "long",
        "size": 1.0,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "pnl": 1.0,
        "pnl_percent": 10.0,
        "leverage": 5.0,
        "open_time": datetime(2026, 7, 1, 10, 0),
        "close_time": datetime(2026, 7, 1, 12, 0),
        "close_reason": "unknown",
    }
    data.update(overrides)
    return PositionHistory(**data)


async def test_route_docstrings_keep_phase0_analytics_contract_truthful():
    performance_doc = analytics_routes.get_performance_metrics.__doc__ or ""
    equity_doc = analytics_routes.get_equity_curve.__doc__ or ""
    route_docs = "\n".join([performance_doc, equity_doc])

    for stale_phrase in [
        "Sharpe ratio, max drawdown",
        "equity is reconstructed from cumulative",
        "realised PnL (``total_pnl_usd``)",
    ]:
        assert stale_phrase not in route_docs

    assert "trade_quality_score" in performance_doc
    assert "realised_pnl_drawdown_*" in performance_doc
    assert "total_balance_usd" in equity_doc
    assert "no_account_equity_data" in equity_doc


async def test_frozen_positions_fixture_pins_reported_mexc_contract(session, user: User):
    assert len(FROZEN_POSITIONS) == 49
    assert round(sum(p["closeProfitLoss"] for p in FROZEN_POSITIONS), 2) == FROZEN_REPORTED_TOTAL_PNL
    assert sum(1 for p in FROZEN_POSITIONS if p["closeProfitLoss"] > 0) == FROZEN_WIN_COUNT
    assert sum(1 for p in FROZEN_POSITIONS if p["closeProfitLoss"] < 0) == FROZEN_LOSS_COUNT

    session.add_all(
        _position(
            user,
            symbol=p["symbol"],
            side=p["side"],
            size=p["size"],
            entry_price=p["entry_price"],
            exit_price=p["exit_price"],
            pnl=p["closeProfitLoss"],
            pnl_percent=p["profitRatio"],
            leverage=p["leverage"],
            open_time=_dt(p["open_time"]),
            close_time=_dt(p["close_time"]),
            close_reason=p["close_reason"],
        )
        for p in FROZEN_POSITIONS
    )
    await session.flush()

    metrics = await analytics_service.compute_performance_metrics(session, user.id, "mexc")

    assert metrics["total_trades"] == 49
    assert metrics["winning_trades"] == 48
    assert metrics["losing_trades"] == 1
    assert metrics["total_pnl"] == FROZEN_REPORTED_TOTAL_PNL
    assert metrics["total_pnl_basis"] == "MEXC-reported closed-position PnL"
    assert metrics["total_pnl_percent"] is None
    assert metrics["total_pnl_percent_reason"] == "capital_history_missing"


async def test_total_pnl_percent_is_unavailable_not_summed_roi(session, user: User):
    session.add_all(
        [
            _position(user, symbol="BTC_USDT", pnl=10.0, pnl_percent=10.0, close_time=datetime(2026, 7, 1, 12, 0)),
            _position(user, symbol="ETH_USDT", pnl=-5.0, pnl_percent=-5.0, close_time=datetime(2026, 7, 2, 12, 0)),
            _position(user, symbol="SOL_USDT", pnl=20.0, pnl_percent=20.0, close_time=datetime(2026, 7, 3, 12, 0)),
        ]
    )
    await session.flush()

    metrics = await analytics_service.compute_performance_metrics(session, user.id, "mexc")

    assert metrics["total_pnl"] == 25.0
    assert metrics["total_pnl_percent"] is None
    assert metrics["total_pnl_percent_reason"] == "capital_history_missing"
    assert metrics["account_return_pct"] is None
    assert metrics["account_return_pct_reason"] == "capital_history_missing"


async def test_benchmark_does_not_turn_closed_position_pnl_into_account_return(
    session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    session.add_all(
        [
            _position(user, symbol="BTC_USDT", pnl=10.0, pnl_percent=10.0, close_time=datetime(2026, 7, 1, 12, 0)),
            _position(user, symbol="ETH_USDT", pnl=-5.0, pnl_percent=-5.0, close_time=datetime(2026, 7, 2, 12, 0)),
            _position(user, symbol="SOL_USDT", pnl=20.0, pnl_percent=20.0, close_time=datetime(2026, 7, 3, 12, 0)),
        ]
    )
    await session.flush()
    monkeypatch.setattr(
        analytics_routes,
        "_fetch_btc_daily_closes",
        lambda symbol, days: [("2026-07-01", 100.0), ("2026-07-02", 110.0)],
    )

    benchmark = await analytics_routes.get_benchmark(
        symbol="BTC-USD",
        days=2,
        exchange="mexc",
        current_user=user,
        session=session,
    )

    assert benchmark.btc_return_pct == 10.0
    assert benchmark.portfolio_return_pct is None
    assert benchmark.alpha is None
    assert benchmark.beta is None
    assert benchmark.basis is None
    assert benchmark.source == "PortfolioSnapshot.total_balance_usd"
    assert benchmark.complete is False
    assert benchmark.unavailable_reason == "capital_history_missing"
    assert [point.portfolio_return_pct for point in benchmark.points] == [None, None]


async def test_empty_performance_keeps_dollars_zero_but_account_return_unavailable(session, user: User):
    metrics = await analytics_service.compute_performance_metrics(session, user.id, "mexc")

    assert metrics["total_pnl"] == 0.0
    assert metrics["total_pnl_percent"] is None
    assert metrics["total_pnl_percent_reason"] == "capital_history_missing"
    assert metrics["account_return_pct"] is None
    assert metrics["account_return_pct_reason"] == "capital_history_missing"
    assert metrics["total_pnl_basis"] == "MEXC-reported closed-position PnL"


async def test_drawdown_and_trade_quality_are_named_by_realised_pnl_basis(session, user: User):
    session.add_all(
        _position(user, symbol=f"BE{i}_USDT", pnl=0.0, pnl_percent=0.0, close_time=datetime(2026, 7, 1, 12, 0) + timedelta(days=i))
        for i in range(49)
    )
    await session.flush()

    metrics = await analytics_service.compute_performance_metrics(session, user.id, "mexc")

    assert metrics["realised_pnl_drawdown_usd"] == 0.0
    assert metrics["realised_pnl_drawdown_pct"] == 0.0
    assert metrics["drawdown_basis"] == "cumulative_closed_pnl"
    assert metrics["trade_quality_score"] is None
    assert metrics["trade_quality_basis"] == "per_trade_pnl_dispersion"
    assert metrics["max_drawdown"] == metrics["realised_pnl_drawdown_usd"]
    assert metrics["max_drawdown_percent"] == metrics["realised_pnl_drawdown_pct"]
    assert metrics["sharpe_ratio"] == metrics["trade_quality_score"]


async def test_equity_curve_does_not_fallback_to_unrealised_or_total_pnl(session, user: User):
    session.add_all(
        [
            PortfolioSnapshot(user_id=user.id, exchange="mexc", total_balance_usd=None, total_pnl_usd=-12.0, open_positions=1, timestamp=datetime(2026, 7, 1, 23, 59)),
            PortfolioSnapshot(user_id=user.id, exchange="mexc", total_balance_usd=None, total_pnl_usd=0.0, open_positions=0, timestamp=datetime(2026, 7, 2, 0, 1)),
        ]
    )
    await session.flush()

    curve = await analytics_service.get_equity_curve(session, user.id, "mexc")

    assert curve["points"] == []
    assert curve["basis"] is None
    assert curve["unavailable_reason"] == "no_account_equity_data"
    assert curve["source"] == "PortfolioSnapshot.total_balance_usd"
    assert curve["complete"] is False


async def test_equity_curve_omits_null_points_from_partial_history(session, user: User):
    session.add_all(
        [
            PortfolioSnapshot(user_id=user.id, exchange="mexc", total_balance_usd=None, total_pnl_usd=7.0, open_positions=1, timestamp=datetime(2026, 7, 1, 23, 59)),
            PortfolioSnapshot(user_id=user.id, exchange="mexc", total_balance_usd=1000.25, total_pnl_usd=8.0, open_positions=1, timestamp=datetime(2026, 7, 2, 0, 1)),
        ]
    )
    await session.flush()

    curve = await analytics_service.get_equity_curve(session, user.id, "mexc")

    assert curve["basis"] == "account_snapshot"
    assert curve["unavailable_reason"] is None
    assert curve["complete"] is False
    assert curve["points"] == [
        {"timestamp": "2026-07-02T00:01:00+00:00", "total_value": 1000.25, "basis": "account_snapshot"}
    ]


async def test_spot_allocation_is_labeled_and_risk_does_not_use_spot_as_futures_denominator(session, user: User, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analytics_routes, "_require_supported_exchange", lambda exchange: exchange.lower())
    session.add_all(
        [
            PortfolioBalance(user_id=user.id, exchange="mexc", asset="USDT", free=100.0, locked=0.0, total=100.0, usd_value=100.0),
            PortfolioBalance(user_id=user.id, exchange="mexc", asset="ADA", free=10.0, locked=0.0, total=10.0, usd_value=5.0),
        ]
    )
    await session.flush()

    allocation = await analytics_service.get_allocation(session, user.id, "mexc")
    risk = await analytics_routes.get_risk_metrics("mexc", current_user=user, session=session)

    assert {item["account_type"] for item in allocation["items"]} == {"spot"}
    assert allocation["account_type"] == "spot"
    assert risk.margin_usage_pct is None
    assert risk.unavailable_reason == "futures_equity_not_available"
    assert risk.risk_reason == "no_open_futures_risk"


async def test_flat_health_is_not_applicable_from_snapshot(session, user: User, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analytics_routes, "_require_supported_exchange", lambda exchange: exchange.lower())
    session.add(
        PortfolioSnapshot(
            user_id=user.id,
            exchange="mexc",
            total_balance_usd=None,
            total_pnl_usd=0.0,
            open_positions=0,
            timestamp=datetime(2026, 7, 23, 12, 0),
        )
    )
    await session.flush()

    health = await analytics_routes.get_health_score("mexc", current_user=user, session=session)

    assert health.health_score is None
    assert health.grade is None
    assert health.health_reason == "no_open_positions"
    assert health.recommendations == ["No open futures risk."]


async def test_missing_health_snapshot_is_unavailable(session, user: User, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analytics_routes, "_require_supported_exchange", lambda exchange: exchange.lower())

    health = await analytics_routes.get_health_score("mexc", current_user=user, session=session)

    assert health.health_score is None
    assert health.grade is None
    assert health.health_reason == "no_snapshot_data"
