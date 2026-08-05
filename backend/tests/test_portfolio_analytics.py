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
from backend.models import (
    CapitalFlowLedger,
    FuturesAccountSnapshot,
    PortfolioBalance,
    PortfolioPosition,
    PortfolioSnapshot,
    PositionHistory,
    User,
)
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
    assert "FuturesAccountSnapshot" in equity_doc
    assert "markers" in equity_doc


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
    # PortfolioSnapshot / total_pnl must never become the equity curve.
    session.add_all(
        [
            PortfolioSnapshot(user_id=user.id, exchange="mexc", total_balance_usd=None, total_pnl_usd=-12.0, open_positions=1, timestamp=datetime(2026, 7, 1, 23, 59)),
            PortfolioSnapshot(user_id=user.id, exchange="mexc", total_balance_usd=9999.0, total_pnl_usd=0.0, open_positions=0, timestamp=datetime(2026, 7, 2, 0, 1)),
        ]
    )
    await session.flush()

    curve = await analytics_service.get_equity_curve(session, user.id, "mexc")

    assert curve["points"] == []
    assert curve["basis"] is None
    assert curve["unavailable_reason"] == "no_account_equity_data"
    assert curve["source"] == "FuturesAccountSnapshot.equity"
    assert curve["complete"] is False
    assert curve["markers"] == []


async def test_equity_curve_resolution_week_and_raw(session, user: User):
    # Two days in week 1, one day in week 2 — week buckets to 2 points.
    t0 = datetime(2026, 7, 6, 0, 0, 0)  # Monday
    t1 = datetime(2026, 7, 7, 12, 0, 0)
    t2 = datetime(2026, 7, 13, 0, 0, 0)  # next Monday
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=100.0, source_ts=t0, synced_at=t0,
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=110.0, source_ts=t1, synced_at=t1,
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=120.0, source_ts=t2, synced_at=t2,
            ),
        ]
    )
    await session.flush()

    week = await analytics_service.get_equity_curve(session, user.id, "mexc", resolution="week")
    assert week["resolution"] == "week"
    assert week["point_count_raw"] == 3
    assert week["point_count_returned"] == 2

    raw = await analytics_service.get_equity_curve(session, user.id, "mexc", resolution="raw")
    assert raw["resolution"] == "raw"
    assert raw["point_count_returned"] == 3


async def test_equity_curve_uses_futures_series_and_external_markers(session, user: User):
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t1 = datetime(2026, 7, 2, 0, 0, 0)
    t_mid = datetime(2026, 7, 1, 12, 0, 0)
    session.add_all(
        [
            # Dust series must not win over USDT.
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="STETH",
                equity=0.0, source_ts=t0, synced_at=t0,
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=t0, synced_at=t0,
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1100.5, source_ts=t1, synced_at=t1,
            ),
            CapitalFlowLedger(
                user_id=user.id, exchange="mexc", entry_type="deposit",
                exchange_entry_id="dep-1", asset="USDT", amount=50.0, signed_amount=50.0,
                occurred_at=t_mid, synced_at=t_mid,
            ),
            # Funding is not an external capital marker.
            CapitalFlowLedger(
                user_id=user.id, exchange="mexc", entry_type="funding",
                exchange_entry_id="fund-1", asset="USDT", amount=1.0, signed_amount=-1.0,
                occurred_at=t_mid, synced_at=t_mid,
            ),
        ]
    )
    await session.flush()

    curve = await analytics_service.get_equity_curve(session, user.id, "mexc")

    assert curve["basis"] == "futures_equity"
    assert curve["settlement_asset"] == "USDT"
    assert curve["unavailable_reason"] is None
    assert curve["complete"] is True
    assert curve["source"] == "FuturesAccountSnapshot.equity"
    assert len(curve["points"]) == 2
    assert curve["points"][0]["total_value"] == 1000.0
    assert curve["points"][1]["total_value"] == 1100.5
    assert len(curve["markers"]) == 1
    assert curve["markers"][0]["entry_type"] == "deposit"
    assert curve["markers"][0]["signed_amount"] == 50.0
    # as_of is the last raw snapshot; small series is not downsampled.
    assert curve["as_of"] is not None
    assert curve["as_of"].startswith("2026-07-02")
    assert curve["point_count_raw"] == 2
    assert curve["point_count_returned"] == 2


def test_downsample_equity_points_keeps_endpoints_and_caps_length():
    """Dense series downsamples but always keeps first/last timestamps."""
    # 400 snapshots across ~40 calendar days (10/day) → daily pass still has 40;
    # force thin path with max_points=20 after daily collapse needs many days.
    points = []
    start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i in range(400):
        # 2 snapshots per day for 200 days → daily last-of-day still 200 → even thin.
        ts = start + timedelta(hours=12 * i)
        points.append(
            {
                "timestamp": ts.isoformat(),
                "total_value": 1000.0 + i,
                "basis": "futures_equity",
                "settlement_asset": "USDT",
            }
        )

    down = analytics_service._downsample_equity_points(points, max_points=200)
    assert len(down) <= 200
    assert down[0]["timestamp"] == points[0]["timestamp"]
    assert down[-1]["timestamp"] == points[-1]["timestamp"]
    assert down[0]["total_value"] == points[0]["total_value"]
    assert down[-1]["total_value"] == points[-1]["total_value"]

    # Prefer last point of each UTC day when under the daily-collapse path.
    # 5 points on day1 + 3 on day2 with max 200 → last-of-day only.
    day1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    multi_day = [
        {"timestamp": (day1 + timedelta(hours=h)).isoformat(), "total_value": float(h), "basis": "futures_equity", "settlement_asset": "USDT"}
        for h in (0, 6, 12, 18, 22)
    ] + [
        {"timestamp": (day1 + timedelta(days=1, hours=h)).isoformat(), "total_value": 100.0 + h, "basis": "futures_equity", "settlement_asset": "USDT"}
        for h in (1, 8, 20)
    ]
    # Force daily path by using a series longer than max_points with few days.
    padded = []
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(205):
        padded.append(
            {
                "timestamp": (base + timedelta(hours=i)).isoformat(),
                "total_value": float(i),
                "basis": "futures_equity",
                "settlement_asset": "USDT",
            }
        )
    daily = analytics_service._downsample_equity_points(padded, max_points=200)
    assert len(daily) <= 200
    assert daily[0]["timestamp"] == padded[0]["timestamp"]
    assert daily[-1]["timestamp"] == padded[-1]["timestamp"]
    # ~9 calendar days → should collapse near one-per-day (+ endpoints already in set).
    assert len(daily) < len(padded)
    assert len(daily) <= 10

    # Sanity: multi-day last-of-day preference (no cap pressure).
    short = multi_day  # 8 points < 200 → unchanged
    assert analytics_service._downsample_equity_points(short) == short


async def test_equity_curve_downsample_as_of_and_markers_preserved(session, user: User):
    """Dense futures snapshots are downsampled; as_of + markers stay full-history."""
    start = datetime(2025, 1, 1, 0, 0, 0)
    snaps = []
    for i in range(250):
        # Multiple snapshots per calendar day so raw count >> returned days.
        ts = start + timedelta(hours=6 * i)
        snaps.append(
            FuturesAccountSnapshot(
                user_id=user.id,
                exchange="mexc",
                settlement_asset="USDT",
                equity=1000.0 + i,
                source_ts=ts,
                synced_at=ts,
            )
        )
    marker_ts = start + timedelta(days=3, hours=3)
    snaps.append(
        CapitalFlowLedger(
            user_id=user.id,
            exchange="mexc",
            entry_type="withdrawal",
            exchange_entry_id="wd-dense-1",
            asset="USDT",
            amount=25.0,
            signed_amount=-25.0,
            occurred_at=marker_ts,
            synced_at=marker_ts,
        )
    )
    session.add_all(snaps)
    await session.flush()

    curve = await analytics_service.get_equity_curve(session, user.id, "mexc")

    assert curve["point_count_raw"] == 250
    assert curve["point_count_returned"] == len(curve["points"])
    assert curve["point_count_returned"] < curve["point_count_raw"]
    assert curve["point_count_returned"] <= analytics_service.MAX_EQUITY_CURVE_POINTS
    assert curve["points"][0]["total_value"] == 1000.0
    assert curve["points"][-1]["total_value"] == 1000.0 + 249
    # as_of is last *raw* snapshot, not a thinned intermediate.
    last_raw_ts = start + timedelta(hours=6 * 249)
    assert curve["as_of"] == analytics_service._iso_ts(last_raw_ts)
    assert len(curve["markers"]) == 1
    assert curve["markers"][0]["entry_type"] == "withdrawal"
    assert curve["markers"][0]["signed_amount"] == -25.0


async def test_equity_curve_empty_includes_as_of_counts(session, user: User):
    curve = await analytics_service.get_equity_curve(session, user.id, "mexc")
    assert curve["points"] == []
    assert curve["as_of"] is None
    assert curve["point_count_raw"] == 0
    assert curve["point_count_returned"] == 0
    assert curve["unavailable_reason"] == "no_account_equity_data"


async def test_account_equity_drawdown_from_futures_series(session, user: User):
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    t1 = datetime(2026, 7, 2, 0, 0, 0)
    t2 = datetime(2026, 7, 3, 0, 0, 0)
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1000.0, source_ts=t0, synced_at=t0,
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=1200.0, source_ts=t1, synced_at=t1,
            ),
            FuturesAccountSnapshot(
                user_id=user.id, exchange="mexc", settlement_asset="USDT",
                equity=900.0, source_ts=t2, synced_at=t2,
            ),
            PositionHistory(
                user_id=user.id, exchange="mexc", symbol="BTCUSDT", side="long",
                size=1.0, entry_price=1.0, exit_price=1.0, pnl=10.0, close_time=t2,
            ),
        ]
    )
    await session.flush()

    metrics = await analytics_service.compute_performance_metrics(session, user.id, "mexc")
    # Peak 1200 → trough 900 = 300 drawdown (25% of peak)
    assert metrics["account_equity_drawdown_usd"] == 300.0
    assert metrics["account_equity_drawdown_pct"] == 25.0
    assert metrics["account_equity_drawdown_reason"] is None
    # Realised PnL drawdown stays separate.
    assert metrics["drawdown_basis"] == "cumulative_closed_pnl"


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
