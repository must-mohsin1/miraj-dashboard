"""Tests for scheduled-scan persistence parity with the manual scan route.

The 4-hour watchlist scheduler must persist the same full normalized scan
result the manual ``POST /scan/{symbol}`` route persists (trimmed of
chart-only series via ``build_persistable_result``), so that
``diff_service`` can do field-level diffs — QQE flips, structure changes,
verdict transitions — across scheduled scans too.

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production \
        .venv/bin/python -m pytest backend/tests/test_scheduler_persistence.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import time)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.database import Base, set_db_path
from backend.models import Analysis, ScanRun, User, WatchlistPair
from backend.services.analysis_service import build_persistable_result

pytestmark = pytest.mark.anyio


# ── Fake full scan result (mirrors run_scan's assembled dict) ────────────────


def _make_full_scan_result(symbol: str = "BTC-USD") -> dict[str, Any]:
    """Build a dict shaped like ``analysis_service.run_scan``'s return value."""
    return {
        "symbol": symbol,
        "overall_score": 61.7,
        "confluence_score": 18.5,
        "score_breakdown": {"total": 18.5, "trade_decision": True},
        "scores": {"regime": 4.0, "location": 3.0, "confirmation": 5.0,
                   "volume_retest": 2.0, "risk": 2.0},
        "trade_plan": {"direction": "LONG", "trade_decision": True},
        "trade_plan_flat": {"direction": "LONG", "entry": 50000.0,
                            "stop_loss": 49500.0, "target_1": 52000.0},
        "verdict": {
            "schema_version": 1,
            "state": "WATCH",
            "display": "WATCH — wait for entry zone",
            "bias": "LONG",
            "actionable": False,
            "gates": [{"key": "regime", "label": "Weekly BMSB regime",
                       "passed": True, "detail": "regime=bull"}],
            "blockers": ["zone: no direction-matched 4H order block"],
            "reasoning": "LONG context is confirmed, wait for a pullback.",
            "next_review": "next 4h scan",
        },
        "macro_data": {"btc_d": 54.2, "usdt_d": 4.6, "dxy": 104.1,
                       "fear_greed": {"value": 55}, "long_short_ratio_btc": 1.1},
        "smc": {"order_blocks": [], "fvgs": []},
        "patterns": {"detected": [{"pattern": "Double Bottom", "confirmed": False}]},
        "bmsb": {"regime": "bull", "current_price": 50250.0},
        "qqe": {
            "daily": {"signal": "GREEN"},
            "4h": {"signal": "GREEN-STRONG"},
            "1h": {"signal": "Neutral"},
        },
        "qqe_signals": {
            "daily": {"trend": "GREEN", "strength": "normal"},
            "4h": {"trend": "GREEN", "strength": "strong"},
            "1h": {"trend": "NEUTRAL", "strength": "none"},
        },
        "structure": {
            "weekly": {"label": "HH"}, "daily": {"label": "HL"},
            "4h": {"label": "HH"}, "1h": {"label": "HL"}, "15m": {"label": "HH"},
        },
        "indicators": {"daily": {"rsi": 58.2, "bb_squeeze": False},
                       "4h": {"rsi": 61.0, "bb_squeeze": True}},
        # Chart-only payloads — must NOT survive persistence
        "candles": [
            {"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
            {"time": 2, "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 200.0},
            {"time": 3, "open": 2.0, "high": 3.0, "low": 1.5, "close": 2.5, "volume": 300.0},
        ],
        "emas": {"21": [1.0, 1.1], "50": [0.9, 1.0]},
        "macd": {"macd": [0.1, 0.2], "signal": [0.05, 0.1], "hist": [0.05, 0.1]},
        "volume_profile": {"bins": [1, 2, 3]},
        "bb": {"upper": [2.0], "mid": [1.5], "lower": [1.0]},
        "rsi": [55.0, 58.2],
        "order_blocks": [{"low": 49000.0, "high": 49500.0, "type": "bullish"}],
        "fvgs": [],
        "stale": False,
        "cached_at": "2026-07-20T00:00:00+00:00",
    }


# ── Unit tests: build_persistable_result ─────────────────────────────────────


class TestBuildPersistableResult:
    def test_drops_chart_series_keys(self):
        trimmed = build_persistable_result(_make_full_scan_result())
        for key in ("emas", "macd", "bb", "rsi", "volume_profile"):
            assert key not in trimmed, f"{key!r} should be stripped"

    def test_keeps_diffable_analytic_keys(self):
        trimmed = build_persistable_result(_make_full_scan_result())
        for key in ("verdict", "qqe", "qqe_signals", "structure", "indicators",
                    "patterns", "trade_plan", "trade_plan_flat", "scores",
                    "score_breakdown", "confluence_score", "overall_score",
                    "smc", "bmsb", "macro_data", "order_blocks", "fvgs"):
            assert key in trimmed, f"{key!r} should be kept"

    def test_trims_candles_to_last_bar(self):
        trimmed = build_persistable_result(_make_full_scan_result())
        assert trimmed["candles"] == [
            {"time": 3, "open": 2.0, "high": 3.0, "low": 1.5, "close": 2.5, "volume": 300.0},
        ]

    def test_tolerates_missing_or_odd_candles(self):
        assert "candles" not in build_persistable_result({"confluence_score": 1.0})
        assert build_persistable_result({"candles": []})["candles"] == []
        assert build_persistable_result({"candles": "n/a"})["candles"] == "n/a"

    def test_does_not_mutate_input(self):
        full = _make_full_scan_result()
        build_persistable_result(full)
        assert len(full["candles"]) == 3
        assert "emas" in full


# ── Integration: run_scheduled_scan persists the full result ─────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="sched_persist_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def db(tmp_db_path: str):
    """Point the backend at a fresh temp DB with all tables created."""
    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(tmp_db_path)

    from backend.database import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


async def test_scheduled_scan_persists_full_normalized_result(db):
    """A scheduled-scan row must carry qqe_signals, structure, and verdict."""
    from backend.database import get_session_factory
    from backend.scheduler import run_scheduled_scan

    factory = get_session_factory()
    async with factory() as session:
        user = User(username="sched", email="sched@example.com",
                    hashed_password="$2b$12$dummyhash")
        session.add(user)
        await session.flush()
        session.add(WatchlistPair(user_id=user.id, pair="BTC-USD"))
        await session.commit()
        user_id = user.id

    fake_result = _make_full_scan_result("BTC-USD")

    with patch("backend.scheduler.run_scan", return_value=fake_result), \
         patch("backend.alerts.manager.process_scan_results",
               new=AsyncMock(return_value=[])):
        await run_scheduled_scan()

    async with factory() as session:
        run_row = (await session.execute(
            select(ScanRun).order_by(ScanRun.id.desc())
        )).scalars().first()
        assert run_row is not None and run_row.status == "completed"

        row = (await session.execute(
            select(Analysis).where(Analysis.user_id == user_id)
        )).scalars().one()

        assert row.analysis_type == "scheduled_scan"
        assert row.pair == "BTC-USD"
        assert row.score == pytest.approx(61.7)

        stored = json.loads(row.result)

        # The required diffable fields — previously missing from scheduled rows.
        assert "qqe_signals" in stored
        assert "structure" in stored
        assert "verdict" in stored
        assert stored["qqe_signals"]["4h"]["trend"] == "GREEN"
        assert stored["structure"]["daily"]["label"] == "HL"
        assert stored["verdict"]["state"] == "WATCH"
        assert stored["verdict"]["bias"] == "LONG"

        # Raw qqe payload (what diff_qqe_signals actually reads) survives too.
        assert stored["qqe"]["daily"]["signal"] == "GREEN"

        # Chart series are trimmed; candles cut to the final bar.
        for key in ("emas", "macd", "bb", "rsi", "volume_profile"):
            assert key not in stored
        assert [c["volume"] for c in stored["candles"]] == [300.0]

        # Blob is byte-identical to what the manual route would persist.
        assert stored == json.loads(
            json.dumps(build_persistable_result(fake_result), default=str)
        )
