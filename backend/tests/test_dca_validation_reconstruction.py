"""Tests for DCA validation scan-history reconstruction service."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import Analysis, PortfolioPosition, User
from backend.services.dca_validation_reconstruction import reconstruct_scan_history

pytestmark = pytest.mark.anyio

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dca_validation_scans.json"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="dca_validation_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def session(tmp_db_path: str):
    from backend import database

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
        username="dcauser",
        email="dca@example.com",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _load_fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


async def _insert_position(session, user_id: int, exchange: str, symbol: str, payload: dict) -> None:
    session.add(
        PortfolioPosition(
            user_id=user_id,
            exchange=exchange,
            symbol=symbol,
            side=payload["side"],
            size=payload["size"],
            entry_price=payload["entry_price"],
            mark_price=payload["mark_price"],
            pnl=payload["pnl"],
            pnl_percent=payload["pnl_percent"],
            leverage=payload["leverage"],
            liquidation_price=payload["liquidation_price"],
            margin=payload["margin"],
        )
    )
    await session.flush()


async def _insert_scan(
    session,
    user_id: int,
    symbol: str,
    created_at: datetime,
    result: dict | str | None,
    exchange: str = "binance",
) -> None:
    encoded = result if isinstance(result, str) else json.dumps(result)
    session.add(
        Analysis(
            user_id=user_id,
            pair=symbol,
            analysis_type="scan",
            parameters=json.dumps({"symbol": symbol, "exchange": exchange}),
            result=encoded,
            score=(result or {}).get("confluence_score") if isinstance(result, dict) else None,
            created_at=created_at,
        )
    )
    await session.flush()


async def _seed_fixture(session, user_id: int, name: str) -> dict:
    fixture = _load_fixtures()[name]
    await _insert_position(
        session,
        user_id,
        fixture["exchange"],
        fixture["symbol"],
        fixture["position"],
    )
    for item in fixture["scans"]:
        await _insert_scan(
            session,
            user_id,
            fixture["symbol"],
            datetime.fromisoformat(item["created_at"]),
            item["result"],
            fixture["exchange"],
        )
    await session.commit()
    return fixture


def _symbol(result: dict, symbol: str) -> dict:
    for item in result["symbols"]:
        if item["symbol"] == symbol:
            return item
    raise AssertionError(f"missing symbol {symbol}")


async def test_reconstructs_long_fixture_with_visible_fill_assumptions(session, user: User) -> None:
    fixture = await _seed_fixture(session, user.id, "long_closed")

    result = await reconstruct_scan_history(session, user.id, fixture["exchange"], symbol=fixture["symbol"])

    coverage = _symbol(result, fixture["symbol"])
    assert coverage["status"] == "metrics_available"
    assert coverage["scan_count"] == 5
    assert coverage["first_scan_at"] == "2026-01-01T00:00:00"
    assert coverage["last_scan_at"] == "2026-01-01T04:00:00"
    assert coverage["max_scan_gap_seconds"] == 3600
    assert coverage["method"] == "scan-to-scan"
    assert result["method_description"] == "scan-history reconstruction; not candle-level historical replay"

    assumptions = result["fill_assumptions"]
    assert assumptions["long_thresholds"] == [30, 24, 16]
    assert assumptions["short_thresholds"] == [80, 92, 95]
    assert assumptions["allocations"] == [20, 20, 60]
    assert assumptions["slippage_percent"] == 0.05
    assert assumptions["fee_percent"] == 0.04

    add_events = [event for event in coverage["events"] if event["recommendation"] == "ADD"]
    assert [event["entry_level"] for event in add_events] == [1, 2, 3]
    assert [event["allocation_percent"] for event in add_events] == [20, 20, 60]
    assert add_events[0]["fill_price"] == pytest.approx(9904.95)
    assert add_events[0]["fee"] == pytest.approx(0.80)
    assert coverage["reconstructed_position"]["status"] == "closed"
    assert coverage["reconstructed_position"]["exit_timestamp"] == "2026-01-01T04:00:00"
    pnl = coverage["pnl"]
    assert pnl["gross_pnl"] == pytest.approx(1687.80, abs=0.01)
    assert pnl["fees"] == pytest.approx(8.68, abs=0.01)
    assert pnl["slippage_impact"] == pytest.approx(10.84, abs=0.01)
    assert pnl["net_pnl"] == pytest.approx(1668.28, abs=0.01)


async def test_reconstructs_short_fixture_as_open_position(session, user: User) -> None:
    fixture = await _seed_fixture(session, user.id, "short_open")

    result = await reconstruct_scan_history(session, user.id, fixture["exchange"], symbol=fixture["symbol"])

    coverage = _symbol(result, fixture["symbol"])
    assert coverage["status"] == "metrics_available"
    add_events = [event for event in coverage["events"] if event["recommendation"] == "ADD"]
    assert [event["entry_level"] for event in add_events] == [1, 2, 3]
    assert add_events[0]["fill_price"] == pytest.approx(2048.975)
    assert coverage["reconstructed_position"]["status"] == "open"
    assert coverage["reconstructed_position"]["valuation_timestamp"] == "2026-01-02T04:00:00"
    assert coverage["pnl"]["gross_pnl"] == pytest.approx(1034.49, abs=0.01)
    assert coverage["pnl"]["fees"] == pytest.approx(7.59, abs=0.01)
    assert coverage["pnl"]["slippage_impact"] == pytest.approx(9.48, abs=0.01)
    assert coverage["pnl"]["net_pnl"] == pytest.approx(1017.42, abs=0.01)


async def test_fewer_than_two_usable_scans_is_insufficient_history(session, user: User) -> None:
    await _insert_position(session, user.id, "binance", "ADAUSDT", {
        "side": "long", "size": 1, "entry_price": 1, "mark_price": 1, "pnl": 0,
        "pnl_percent": 0, "leverage": 1, "liquidation_price": None, "margin": 10000,
    })
    await _insert_scan(session, user.id, "ADAUSDT", datetime(2026, 1, 1), {
        "mark_price": 1.0,
        "trade_plan": {"direction": "LONG"},
        "indicators": {"daily": {"rsi": 31}},
    })
    await session.commit()

    result = await reconstruct_scan_history(session, user.id, "binance", symbol="ADAUSDT")

    coverage = _symbol(result, "ADAUSDT")
    assert coverage["status"] == "insufficient_history"
    assert coverage["required_minimum_scans"] == 2
    assert coverage["events"] == []
    assert coverage["pnl"] is None


@pytest.mark.parametrize(
    ("scan_result", "reason"),
    [
        ({"mark_price": 1.0, "indicators": {"daily": {"rsi": 25}}}, "missing_trade_plan"),
        ({"mark_price": 1.0, "trade_plan": {"direction": "LONG"}}, "missing_rsi"),
        ({"trade_plan": {"direction": "LONG"}, "indicators": {"daily": {"rsi": 25}}}, "missing_mark_price"),
        ("{not-json", "malformed_scan_result"),
        ({"mark_price": 1.0, "trade_plan": {"direction": "SIDEWAYS"}, "indicators": {"daily": {"rsi": 25}}}, "unsupported_direction"),
    ],
)
async def test_skips_unusable_scans_with_machine_readable_reasons(session, user: User, scan_result, reason) -> None:
    await _insert_position(session, user.id, "binance", "XRPUSDT", {
        "side": "long", "size": 1, "entry_price": 1, "mark_price": 1, "pnl": 0,
        "pnl_percent": 0, "leverage": 1, "liquidation_price": None, "margin": 10000,
    })
    await _insert_scan(session, user.id, "XRPUSDT", datetime(2026, 1, 1), scan_result)
    await session.commit()

    result = await reconstruct_scan_history(session, user.id, "binance", symbol="XRPUSDT")

    coverage = _symbol(result, "XRPUSDT")
    assert coverage["skipped_scans"][0]["reason"] == reason
    assert coverage["scan_count"] == 0
    assert coverage["status"] == "insufficient_history"


async def test_missing_position_context_skips_scans(session, user: User) -> None:
    await _insert_scan(session, user.id, "SOLUSDT", datetime(2026, 1, 1), {
        "mark_price": 100.0,
        "trade_plan": {"direction": "LONG"},
        "indicators": {"daily": {"rsi": 25}},
    })
    await session.commit()

    result = await reconstruct_scan_history(session, user.id, "binance", symbol="SOLUSDT")

    coverage = _symbol(result, "SOLUSDT")
    assert coverage["skipped_scans"][0]["reason"] == "missing_position_context"
    assert coverage["scan_count"] == 0


async def test_scan_gaps_over_48_hours_are_reported(session, user: User) -> None:
    await _insert_position(session, user.id, "binance", "DOGEUSDT", {
        "side": "long", "size": 1, "entry_price": 1, "mark_price": 1, "pnl": 0,
        "pnl_percent": 0, "leverage": 1, "liquidation_price": None, "margin": 10000,
    })
    first = datetime(2026, 1, 1)
    await _insert_scan(session, user.id, "DOGEUSDT", first, {
        "mark_price": 1.0,
        "trade_plan": {"direction": "LONG"},
        "indicators": {"daily": {"rsi": 31}},
    })
    await _insert_scan(session, user.id, "DOGEUSDT", first + timedelta(hours=49), {
        "mark_price": 0.9,
        "trade_plan": {"direction": "LONG"},
        "indicators": {"daily": {"rsi": 29}},
    })
    await session.commit()

    result = await reconstruct_scan_history(session, user.id, "binance", symbol="DOGEUSDT")

    coverage = _symbol(result, "DOGEUSDT")
    assert coverage["max_scan_gap_seconds"] == 49 * 3600
    assert coverage["data_quality_warnings"] == ["scan_gap_over_48_hours"]
    assert coverage["events"][0]["fill_assumption"] == "assumed_scan_gap_over_48h"
