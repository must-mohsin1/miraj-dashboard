"""Phase 1 closed-position analytics calculator correctness tests."""

from __future__ import annotations

import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import create_access_token, hash_password
from backend.database import Base, set_db_path
from backend.models import PositionHistory, User
from backend.services import analytics_service
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
    fd, path = tempfile.mkstemp(suffix=".db", prefix="closed_position_phase1_")
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
        username="closedpositionphase1",
        email="closedpositionphase1@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _make_user(session, username: str) -> User:
    user = User(username=username, email=f"{username}@test.local", hashed_password=hash_password("testpass123"))
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc).replace(tzinfo=None)


def _position(user: User, exchange: str = "mexc", **overrides: Any) -> PositionHistory:
    data = {
        "user_id": user.id,
        "exchange": exchange,
        "symbol": "BTC_USDT",
        "side": "long",
        "size": 1.0,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "pnl": 1.0,
        "pnl_percent": 1.0,
        "leverage": 5.0,
        "open_time": datetime(2026, 7, 1, 10, 0),
        "close_time": datetime(2026, 7, 1, 12, 0),
        "close_reason": "manual",
        "contract_size": 1.0,
    }
    data.update(overrides)
    return PositionHistory(**data)


def _frozen_position(user: User, row: dict[str, Any], exchange: str = "mexc") -> PositionHistory:
    return _position(
        user,
        exchange=exchange,
        symbol=row["symbol"],
        side=row["side"],
        size=row["size"],
        entry_price=row["entry_price"],
        exit_price=row["exit_price"],
        pnl=row["closeProfitLoss"],
        pnl_percent=row["profitRatio"],
        leverage=row["leverage"],
        open_time=_dt(row["open_time"]),
        close_time=_dt(row["close_time"]),
        close_reason=row["close_reason"],
    )


def _walk_numbers(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_numbers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_numbers(child)
    elif isinstance(value, float):
        yield value


async def test_frozen_fixture_overview_reconciles_with_decimal_runtime_helpers(session, user: User):
    session.add_all(_frozen_position(user, row) for row in FROZEN_POSITIONS)
    await session.flush()

    analytics = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc")
    expected = expected_closed_position_totals(FROZEN_POSITIONS)
    overview = analytics["overview"]

    assert overview["total_trades"] == 49
    assert overview["winning_trades"] == expected["winning_trades"] == 48
    assert overview["losing_trades"] == expected["losing_trades"] == 1
    assert overview["breakeven_trades"] == expected["breakeven_trades"] == 0
    assert Decimal(str(overview["average_win"])) == Decimal("1.05")
    assert Decimal(str(overview["average_loss"])) == Decimal("-1.17")
    assert Decimal(str(overview["total_pnl"])) == Decimal(str(FROZEN_REPORTED_TOTAL_PNL))
    assert Decimal(str(overview["expectancy_per_trade"])) == expected["expectancy_per_trade"].quantize(Decimal("0.01"))
    assert analytics["basis"]["currency_unit"] == "USDT"
    assert analytics["basis"]["pnl_basis"] == "MEXC-reported closed-position PnL"
    assert analytics["basis"]["fee_status"] == "fee_net_pnl_unavailable_phase2_ledger_required"
    assert analytics["history"]["history_completeness"] == "unknown"
    assert analytics["history"]["reason"] == "full_history_sync_not_implemented_phase2"
    assert analytics["unavailable"]["fee_net_pnl"]["reason"] == "fee_net_pnl_unavailable_phase2_ledger_required"
    assert all(math.isfinite(number) for number in _walk_numbers(analytics))


async def test_auth_exchange_and_shared_filters_reconcile_across_sections(session, user: User):
    other = await _make_user(session, "otherclosedposition")
    session.add_all(
        [
            _position(user, symbol="BTC_USDT", side="long", pnl=10.10, close_time=datetime(2026, 7, 1, 12), close_reason="tp"),
            _position(user, symbol="ETH_USDT", side="short", pnl=-2.25, close_time=datetime(2026, 7, 2, 12), close_reason="sl"),
            _position(user, exchange="binance", symbol="BTC_USDT", side="long", pnl=99.0, close_time=datetime(2026, 7, 3, 12)),
            _position(other, symbol="BTC_USDT", side="long", pnl=88.0, close_time=datetime(2026, 7, 4, 12)),
        ]
    )
    await session.flush()

    filters = {"symbols": ["btc_usdt"], "side": "long", "from": datetime(2026, 7, 1, 12), "to": datetime(2026, 7, 2, 12)}
    analytics = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", filters=filters, period="day")

    assert analytics["overview"]["total_trades"] == 1
    assert analytics["overview"]["total_pnl"] == 10.10
    assert analytics["history"]["row_count"] == 1
    assert analytics["periods"]["totals"] == {"trade_count": 1, "total_pnl": 10.10}
    assert analytics["calendar_days"][0]["total_pnl"] == 10.10
    assert analytics["explorer"]["total"] == 1
    assert analytics["explorer"]["items"][0]["symbol"] == "BTC_USDT"
    assert analytics["filters_applied"] == analytics["periods"]["filters_applied"] == analytics["explorer"]["filters_applied"]


async def test_timezone_calendar_and_period_rollovers_use_half_open_bounds(session, user: User):
    session.add_all(
        [
            _position(user, symbol="A_USDT", pnl=1.0, close_time=datetime(2026, 12, 31, 19, 30), open_time=datetime(2026, 12, 31, 18, 30)),
            _position(user, symbol="B_USDT", pnl=2.0, close_time=datetime(2026, 12, 31, 23, 30), open_time=datetime(2026, 12, 31, 22, 30)),
            _position(user, symbol="C_USDT", pnl=3.0, close_time=datetime(2027, 1, 1, 0, 0), open_time=datetime(2026, 12, 31, 23, 0)),
        ]
    )
    await session.flush()

    utc = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", filters={"to": datetime(2027, 1, 1, 0, 0)}, timezone_name="UTC", period="day")
    karachi = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", filters={"to": datetime(2027, 1, 1, 0, 0)}, timezone_name="Asia/Karachi", period="day")
    weekly = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", timezone_name="UTC", period="week")
    monthly = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", timezone_name="UTC", period="month")

    assert utc["overview"]["total_trades"] == 2
    assert [item["label"] for item in utc["periods"]["items"]] == ["2026-12-31"]
    assert [item["label"] for item in karachi["periods"]["items"]] == ["2027-01-01"]
    assert utc["overview"]["calendar_days"] == 1
    assert karachi["overview"]["calendar_days"] == 1
    from_only = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", filters={"from": datetime(2026, 12, 31, 23, 0)}, timezone_name="UTC", period="day")
    to_only = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", filters={"to": datetime(2027, 1, 2, 0, 0)}, timezone_name="UTC", period="day")
    assert from_only["overview"]["calendar_days"] == 2
    assert to_only["overview"]["calendar_days"] == 2
    assert [item["label"] for item in weekly["periods"]["items"]] == ["2026-W53"]
    assert [item["label"] for item in monthly["periods"]["items"]] == ["2026-12", "2027-01"]

    with pytest.raises(ValueError, match="Invalid timezone"):
        await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", timezone_name="Not/AZone")


async def test_expectancy_profit_factor_streaks_and_null_reasons(session, user: User):
    session.add_all(
        [
            _position(user, symbol="W1_USDT", pnl=2.0, close_time=datetime(2026, 7, 1, 12)),
            _position(user, symbol="L1_USDT", pnl=-1.0, close_time=datetime(2026, 7, 2, 12)),
            _position(user, symbol="W2_USDT", pnl=3.0, close_time=datetime(2026, 7, 3, 12)),
            _position(user, symbol="BE_USDT", pnl=0.0, close_time=datetime(2026, 7, 4, 12)),
        ]
    )
    await session.flush()

    analytics = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc")
    overview = analytics["overview"]

    assert overview["expectancy_per_trade"] == overview["average_trade_pnl"] == 1.0
    weighted = (overview["winning_trades"] / overview["total_trades"] * overview["average_win"]) + (overview["losing_trades"] / overview["total_trades"] * overview["average_loss"])
    assert round(weighted, 2) == overview["expectancy_per_trade"]
    assert overview["payoff_ratio"] == 2.5
    assert overview["profit_factor"] == 5.0
    assert overview["max_win_streak"] == 1
    assert overview["max_loss_streak"] == 1
    assert overview["current_streak"] == {"type": "breakeven", "length": 1}

    no_loss = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", filters={"pnl_min": 0.01})
    assert no_loss["overview"]["profit_factor"] is None
    assert no_loss["overview"]["profit_factor_reason"] == "no_losing_trades"
    assert no_loss["overview"]["payoff_ratio"] is None
    assert no_loss["overview"]["payoff_ratio_reason"] == "no_losing_trades"

    empty = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", filters={"symbols": ["NOPE_USDT"]})
    assert empty["overview"]["win_rate_pct"] is None
    assert empty["overview"]["win_rate_pct_reason"] == "insufficient_data"
    assert empty["overview"]["current_streak"] is None
    assert empty["overview"]["current_streak_reason"] == "insufficient_data"


async def test_concentration_and_breakdowns_use_gross_nonnegative_denominators(session, user: User):
    session.add_all(
        [
            _position(user, symbol="BTC_USDT", side="long", pnl=8.0, open_time=datetime(2026, 7, 1, 11, 30), close_time=datetime(2026, 7, 1, 12), leverage=3),
            _position(user, symbol="BTC_USDT", side="short", pnl=-2.0, open_time=datetime(2026, 6, 30, 12), close_time=datetime(2026, 7, 2, 12), leverage=8),
            _position(user, symbol="ETH_USDT", side="long", pnl=2.0, open_time=datetime(2026, 6, 25, 12), close_time=datetime(2026, 7, 3, 12), leverage=12),
            _position(user, symbol="SOL_USDT", side="short", pnl=-3.0, close_time=datetime(2026, 7, 4, 12), leverage=0, open_time=None),
        ]
    )
    await session.flush()

    analytics = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc")
    concentration = analytics["concentration"]
    assert concentration["gross_profit_top_1_contribution_pct"] == 80.0
    assert concentration["gross_profit_hhi"] == 0.68
    assert concentration["gross_loss_top_1_contribution_pct"] == 60.0
    assert concentration["gross_loss_hhi"] == 0.52

    for group_name in ["symbol", "side", "duration", "leverage", "pair_direction"]:
        rows = analytics["breakdowns"][group_name]
        assert round(sum(row["total_pnl"] for row in rows), 2) == analytics["overview"]["total_pnl"]
        assert sum(row["trade_count"] for row in rows) == analytics["overview"]["total_trades"]

    assert {"<1d", "1-7d", ">7d", "unknown_duration"}.issubset({row["key"] for row in analytics["breakdowns"]["duration"]})
    assert {"<=5x", ">5x-10x", ">10x", "unknown_leverage"}.issubset({row["key"] for row in analytics["breakdowns"]["leverage"]})

    filtered = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", filters={"leverage_min": 1, "duration_min_minutes": 1})
    assert filtered["excluded_reasons"] == {"missing_duration": 1, "missing_leverage": 1}
    assert filtered["overview"]["total_trades"] == 3


async def test_explorer_pagination_sort_filters_and_row_unavailable_reasons(session, user: User):
    session.add_all(
        [
            _position(user, symbol="BTC_USDT", side="long", pnl=1.0, close_time=datetime(2026, 7, 1, 12), leverage=3, close_reason="tp"),
            _position(user, symbol="ETH_USDT", side="short", pnl=1.0, close_time=datetime(2026, 7, 1, 12), leverage=7, close_reason="tp"),
            _position(user, symbol="SOL_USDT", side="long", pnl=-5.0, close_time=datetime(2026, 7, 3, 12), leverage=12, close_reason="sl"),
        ]
    )
    await session.flush()

    default_page = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc")
    assert default_page["explorer"]["limit"] == 50
    assert [item["symbol"] for item in default_page["explorer"]["items"]] == ["SOL_USDT", "BTC_USDT", "ETH_USDT"]

    first_page = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", pagination={"limit": 2, "offset": 0}, sort="pnl")
    assert first_page["explorer"]["limit"] == 2
    assert first_page["explorer"]["total"] == 3
    assert first_page["explorer"]["has_more"] is True
    assert [item["pnl"] for item in first_page["explorer"]["items"]] == [-5.0, 1.0]

    filtered = await analytics_service.compute_closed_position_analytics(
        session,
        user.id,
        "mexc",
        filters={"side": "long", "pnl_max": 1, "close_reason": ["tp", "sl"], "duration_max_minutes": 180, "leverage_max": 5},
        sort="-close_time",
    )
    assert filtered["explorer"]["total"] == 1
    row = filtered["explorer"]["items"][0]
    assert row["symbol"] == "BTC_USDT"
    assert row["currency_unit"] == "USDT"
    assert row["fee_status"] == "fee_net_pnl_unavailable_phase2_ledger_required"
    assert row["unavailable_reasons"]["fee_net_pnl"] == "fee_net_pnl_unavailable_phase2_ledger_required"

    with pytest.raises(ValueError, match="limit must be <= 200"):
        await analytics_service.compute_closed_position_analytics(session, user.id, "mexc", pagination={"limit": 201})


async def test_explorer_row_reports_missing_duration_and_leverage_reasons(session, user: User):
    session.add(
        _position(
            user,
            symbol="MISSING_USDT",
            open_time=None,
            close_time=datetime(2026, 7, 5, 12),
            leverage=0.0,
            contract_size=None,
        )
    )
    await session.flush()

    analytics = await analytics_service.compute_closed_position_analytics(session, user.id, "mexc")
    row = analytics["explorer"]["items"][0]

    assert row["symbol"] == "MISSING_USDT"
    assert row["duration_minutes"] is None
    assert row["leverage"] is None
    assert row["unavailable_reasons"] == {
        "fee_net_pnl": "fee_net_pnl_unavailable_phase2_ledger_required",
        "missing_duration": True,
        "missing_leverage": True,
    }


async def test_phase1_http_routes_require_jwt_and_validate_timezone_and_limit(session, user: User, monkeypatch: pytest.MonkeyPatch):
    from backend.main import app
    from backend.routes import analytics as analytics_routes

    monkeypatch.setattr(analytics_routes, "_require_supported_exchange", lambda exchange: exchange.lower())
    await session.commit()
    token = create_access_token(data={"sub": str(user.id)})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthenticated = await client.get("/api/v1/analytics/mexc/closed-position-analytics")
        assert unauthenticated.status_code == 401

        invalid_timezone = await client.get(
            "/api/v1/analytics/mexc/closed-position-analytics?timezone=Not/AZone",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert invalid_timezone.status_code == 400
        assert "Invalid timezone" in invalid_timezone.json()["detail"]

        oversized_limit = await client.get(
            "/api/v1/analytics/mexc/trade-explorer?limit=201",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert oversized_limit.status_code == 422


async def test_phase1_http_routes_are_auth_exchange_isolated_and_reconcile(session, user: User, monkeypatch: pytest.MonkeyPatch):
    from backend.main import app
    from backend.routes import analytics as analytics_routes

    other = await _make_user(session, "routeotherclosedposition")
    session.add_all(
        [
            _position(user, symbol="BTC_USDT", side="long", pnl=10.10, close_time=datetime(2026, 7, 1, 12), close_reason="tp"),
            _position(user, symbol="ETH_USDT", side="short", pnl=-2.25, close_time=datetime(2026, 7, 2, 12), close_reason="sl"),
            _position(user, exchange="binance", symbol="BTC_USDT", side="long", pnl=99.0, close_time=datetime(2026, 7, 3, 12)),
            _position(other, symbol="BTC_USDT", side="long", pnl=88.0, close_time=datetime(2026, 7, 4, 12)),
        ]
    )
    await session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    monkeypatch.setattr(analytics_routes, "_require_supported_exchange", lambda exchange: exchange.lower())
    headers = {"Authorization": f"Bearer {token}"}
    query = "symbols=btc_usdt&side=long&from=2026-07-01T12:00:00&to=2026-07-02T12:00:00&period=day"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        aggregate = await client.get(f"/api/v1/analytics/mexc/closed-position-analytics?{query}", headers=headers)
        periods = await client.get(f"/api/v1/analytics/mexc/closed-position-periods?{query}", headers=headers)
        breakdown = await client.get(f"/api/v1/analytics/mexc/closed-position-breakdowns?{query}&group_by=symbol", headers=headers)
        explorer = await client.get(f"/api/v1/analytics/mexc/trade-explorer?{query}&limit=200", headers=headers)

    assert aggregate.status_code == 200
    assert periods.status_code == 200
    assert breakdown.status_code == 200
    assert explorer.status_code == 200

    aggregate_json = aggregate.json()
    periods_json = periods.json()
    breakdown_json = breakdown.json()
    explorer_json = explorer.json()
    assert aggregate_json["overview"]["total_trades"] == 1
    assert aggregate_json["overview"]["total_pnl"] == 10.10
    assert aggregate_json["history"]["row_count"] == 1
    assert aggregate_json["filters_applied"] == periods_json["filters_applied"] == explorer_json["filters_applied"]
    assert periods_json["totals"] == {"trade_count": 1, "total_pnl": 10.10}
    assert breakdown_json["items"] == [aggregate_json["breakdowns"]["symbol"][0]]
    assert explorer_json["limit"] == 200
    assert explorer_json["total"] == 1
    assert explorer_json["items"][0]["symbol"] == "BTC_USDT"
    assert explorer_json["items"][0]["currency_unit"] == "USDT"
