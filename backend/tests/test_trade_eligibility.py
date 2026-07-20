"""Regression tests for direction-neutral and price-realistic trade plans."""
from __future__ import annotations

import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.analysis_service import _determine_trade_direction, _extract_price_levels


def _daily_at(price: float = 100.0) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=30, freq="D")
    return pd.DataFrame(
        {
            "Open": [price] * 30,
            "High": [price + 1] * 30,
            "Low": [price - 1] * 30,
            "Close": [price] * 30,
        },
        index=index,
    )


def test_conflicting_structure_and_momentum_returns_no_direction():
    direction = _determine_trade_direction(
        {"weekly": {"label": "HH"}, "daily": {"label": "LH"}, "4h": {"label": "LL"}},
        {"daily": {"trend": "RED"}, "4h": {"trend": "GREEN"}, "1h": {"trend": "RED"}},
        {"regime": "bear"},
    )

    assert direction is None


def test_aligned_bullish_context_returns_long():
    direction = _determine_trade_direction(
        {"weekly": {"label": "HH"}, "daily": {"label": "HH"}, "4h": {"label": "HH"}},
        {"daily": {"trend": "GREEN"}, "4h": {"trend": "GREEN"}, "1h": {"trend": "GREEN"}},
        {"regime": "bull"},
    )

    assert direction == "LONG"


def test_long_uses_only_nearby_bullish_order_block_not_bearish_supply():
    smc = {
        "order_blocks": [
            {"type": "Bearish", "zone": (105.0, 106.0)},
            {"type": "Bullish", "zone": (98.0, 99.0)},
        ]
    }

    levels = _extract_price_levels(
        {"daily": _daily_at()}, smc, direction="LONG", require_actionable_zone=True
    )

    assert levels["entry_zone_low"] == 98.0
    assert levels["entry_zone_high"] == 99.0
    assert levels["entry_is_actionable"] is True


def test_far_order_block_is_not_an_actionable_entry():
    smc = {"order_blocks": [{"type": "Bullish", "zone": (80.0, 81.0)}]}

    levels = _extract_price_levels(
        {"daily": _daily_at()}, smc, direction="LONG", require_actionable_zone=True
    )

    assert levels["entry_is_actionable"] is False
    assert "entry_zone_low" not in levels
