"""Tests for _extract_price_levels and _extract_atr in analysis_service.

Run with::

    cd <project-root>
    python -m pytest backend/tests/test_price_levels.py -v

Covers:
- ATR-based stop loss ≠ entry price (the H01-H02 bug)
- Stop loss direction (LONG below entry, SHORT above)
- Take-profit levels as risk multiples (1R, 2R)
- Fallback to percentage offset when ATR unavailable
- Edge cases: no order blocks, missing columns, short data
"""

from __future__ import annotations

import os
import sys
from typing import Any

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.analysis_service import (
    _extract_atr,
    _extract_price_levels,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_daily(
    num_bars: int = 200,
    price_base: float = 62000.0,
    atr_approx: float = 800.0,
) -> pd.DataFrame:
    """Build a synthetic daily OHLCV DataFrame with realistic ATR."""
    np.random.seed(42)
    idx = pd.date_range("2024-01-01", periods=num_bars, freq="D")
    closes = np.cumsum(np.random.randn(num_bars) * atr_approx / 3.0) + price_base
    highs = closes + np.abs(np.random.randn(num_bars)) * atr_approx / 4.0
    lows = closes - np.abs(np.random.randn(num_bars)) * atr_approx / 4.0
    opens = lows + (highs - lows) * np.random.rand(num_bars)
    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": np.minimum(lows, opens - 1.0),  # ensure low <= open
            "Close": closes,
            "Volume": np.random.randint(1000, 10000, num_bars),
        },
        index=idx,
    )


def _smc_result(zone_low: float = 61800.0, zone_high: float = 62000.0) -> dict:
    """Return a minimal SMC result with one order block."""
    return {
        "order_blocks": [
            {
                "type": "Bullish",
                "zone": (zone_low, zone_high),
                "index": pd.Timestamp("2024-03-01"),
            }
        ],
        "fvgs": [],
        "divergences": [],
        "liquidity_grabs": [],
        "trend_lines": [],
    }


def _empty_smc() -> dict:
    """Return SMC result with no order blocks."""
    return {
        "order_blocks": [],
        "fvgs": [],
        "divergences": [],
        "liquidity_grabs": [],
        "trend_lines": [],
    }


# ── _extract_atr tests ──────────────────────────────────────────────────────


class TestExtractATR:
    def test_returns_positive_float(self):
        df = _make_daily()
        val = _extract_atr(df)
        assert val is not None
        assert val > 0

    def test_none_for_missing_columns(self):
        df = pd.DataFrame({"Open": [1.0], "Close": [2.0]})  # missing High, Low
        assert _extract_atr(df) is None

    def test_none_for_none_input(self):
        assert _extract_atr(None) is None

    def test_none_for_short_data(self):
        df = pd.DataFrame(
            {"High": [100.0], "Low": [99.0], "Close": [99.5]},
            index=pd.date_range("2024-01-01", periods=1, freq="D"),
        )
        assert _extract_atr(df) is None


# ── _extract_price_levels tests ─────────────────────────────────────────────


class TestExtractPriceLevels:
    """Core fix: stop loss MUST NOT equal entry price."""

    def test_stop_not_equal_entry_with_order_block(self):
        """With order block + daily data, stop_loss < entry for LONG."""
        daily = _make_daily(price_base=62223.0)
        timeframes = {"daily": daily}
        smc = _smc_result(zone_low=62000.0, zone_high=62100.0)

        levels = _extract_price_levels(timeframes, smc, direction="LONG")

        assert "stop_loss" in levels
        assert "entry_zone_low" in levels
        entry = levels.get("entry_zone_low")
        stop = levels.get("stop_loss")
        assert entry is not None
        assert stop is not None
        assert stop < entry, f"Stop {stop} must be < entry {entry} for LONG"
        assert abs(stop - entry) > 0.01, "Stop must be materially different from entry"

    def test_stop_below_entry_for_long(self):
        """LONG direction places stop loss below entry."""
        daily = _make_daily()
        timeframes = {"daily": daily}
        smc = _smc_result(zone_low=62000.0, zone_high=62100.0)

        levels = _extract_price_levels(timeframes, smc, direction="LONG")

        entry = levels.get("entry_zone_low")
        stop = levels.get("stop_loss")
        assert stop < entry

    def test_stop_above_entry_for_short(self):
        """SHORT direction places stop loss above entry."""
        daily = _make_daily()
        timeframes = {"daily": daily}
        smc = _smc_result(zone_low=62000.0, zone_high=62100.0)

        levels = _extract_price_levels(timeframes, smc, direction="SHORT")

        entry = levels.get("entry_zone_low")
        stop = levels.get("stop_loss")
        assert stop > entry

    def test_take_profit_levels_as_risk_multiples(self):
        """TP1 is ~1R and TP2 is ~2R from entry."""
        daily = _make_daily()
        timeframes = {"daily": daily}
        smc = _smc_result(zone_low=62000.0, zone_high=62100.0)

        levels = _extract_price_levels(timeframes, smc, direction="LONG")

        entry = levels["entry_zone_low"]
        stop = levels["stop_loss"]
        tp1 = levels["take_profit_1"]
        tp2 = levels["take_profit_2"]

        risk = entry - stop
        assert abs((tp1 - entry) - risk) < 0.02  # TP1 ≈ 1R
        assert abs((tp2 - entry) - 2.0 * risk) < 0.02  # TP2 ≈ 2R

    def test_fallback_when_no_order_blocks(self):
        """When no OB exists, entry = current_price and stop is % offset."""
        daily = _make_daily()
        timeframes = {"daily": daily}
        smc = _empty_smc()

        levels = _extract_price_levels(timeframes, smc, direction="LONG")

        assert "stop_loss" in levels
        cp = levels["current_price"]
        stop = levels["stop_loss"]
        # Stop should be below current price for LONG fallback
        assert stop < cp
        # Stop should be within 5% (risk_percent ≈ 0.5%)
        assert (cp - stop) / cp < 0.05

    def test_no_daily_data_returns_basic_levels(self):
        """Without daily OHLCV, only non-price fields are returned."""
        levels = _extract_price_levels(
            {"daily": pd.DataFrame()}, _empty_smc(), direction="LONG"
        )
        # No current_price → no entry → function returns early
        assert "stop_loss" not in levels
        assert "current_price" not in levels

    def test_zero_risk_distance_guarded(self):
        """If ATR and % offset both produce zero offset, floor at 1 cent."""
        daily = _make_daily(num_bars=200, price_base=100.0, atr_approx=0.001)
        timeframes = {"daily": daily}
        smc = _smc_result(zone_low=99.0, zone_high=101.0)

        levels = _extract_price_levels(timeframes, smc, direction="LONG")

        stop = levels.get("stop_loss")
        entry = levels.get("entry_zone_low")
        assert stop is not None and entry is not None
        assert entry - stop >= 0.01, "Minimum stop offset must be 1 cent"

    def test_fallback_when_atr_unavailable(self):
        """When ATR can't compute (too few bars), use % offset fallback."""
        daily = _make_daily(num_bars=5)  # too short for 14-period ATR
        timeframes = {"daily": daily}
        smc = _smc_result(zone_low=62000.0, zone_high=62100.0)

        levels = _extract_price_levels(timeframes, smc, direction="LONG")

        assert "stop_loss" in levels
        stop = levels["stop_loss"]
        entry = levels["entry_zone_low"]
        assert stop < entry  # fallback still produces valid offset

    def test_default_direction_is_long(self):
        """Omitting direction defaults to LONG."""
        daily = _make_daily()
        timeframes = {"daily": daily}
        smc = _smc_result(zone_low=62000.0, zone_high=62100.0)

        levels = _extract_price_levels(timeframes, smc)

        entry = levels.get("entry_zone_low")
        stop = levels.get("stop_loss")
        assert stop < entry  # LONG behaviour

    def test_entry_zone_low_is_none_still_works(self):
        """When OB zone low is None, fallback to current_price as entry."""
        smc_no_low = {
            "order_blocks": [{"type": "Bullish", "zone": (None, None)}],
            "fvgs": [],
            "divergences": [],
            "liquidity_grabs": [],
            "trend_lines": [],
        }
        daily = _make_daily()
        timeframes = {"daily": daily}

        levels = _extract_price_levels(timeframes, smc_no_low, direction="LONG")

        assert "stop_loss" in levels
        assert levels["stop_loss"] < levels["current_price"]

    def test_stop_never_shares_value_with_entry(self):
        """Verify stop_loss != entry_price under every reasonable data scenario."""
        for price_base in (100.0, 1000.0, 50000.0, 100000.0):
            daily = _make_daily(price_base=price_base)
            timeframes = {"daily": daily}
            smc = _smc_result(
                zone_low=price_base * 0.99, zone_high=price_base * 1.01
            )

            levels = _extract_price_levels(timeframes, smc, direction="LONG")
            entry = levels.get("entry_zone_low")
            stop = levels.get("stop_loss")
            assert entry is not None and stop is not None
            assert (
                abs(entry - stop) > 0.01
            ), f"Stop matches entry at price ${price_base}"

            levels_short = _extract_price_levels(timeframes, smc, direction="SHORT")
            entry_s = levels_short.get("entry_zone_low")
            stop_s = levels_short.get("stop_loss")
            assert entry_s is not None and stop_s is not None
            assert (
                abs(entry_s - stop_s) > 0.01
            ), f"Stop matches entry at SHORT price ${price_base}"
