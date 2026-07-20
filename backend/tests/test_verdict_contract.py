"""Regression fixtures for the typed scan-verdict contract.

Covers the scenario matrix that produced the July forced-long defect:
bull-aligned, bear-aligned, mixed/conflicting, distant (stale) zone,
missing regime data, and a 2R path blocked by an opposing zone.

Also covers the detection-time zone metadata (smc.annotate_zones): the
annotated ``actionable`` flag must agree with the selection-time zone
gate, and the metadata must survive the UI normalizers additively.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.analysis_service import (
    _determine_trade_direction,
    _extract_price_levels,
    _normalize_fvgs,
    _normalize_obs,
)
from mirai_core import smc as smc_module
from mirai_core.verdict import Bias, ScanVerdict, build_verdict, derive_bias


BULL_STRUCTURE = {"weekly": {"label": "HH"}, "daily": {"label": "HH"}, "4h": {"label": "HL"}}
BEAR_STRUCTURE = {"weekly": {"label": "LH"}, "daily": {"label": "LL"}, "4h": {"label": "LL"}}
MIXED_STRUCTURE = {"weekly": {"label": "HH"}, "daily": {"label": "LH"}, "4h": {"label": "LL"}}

GREEN_QQE = {"daily": {"trend": "GREEN"}, "4h": {"trend": "GREEN"}, "1h": {"trend": "GREEN"}}
RED_QQE = {"daily": {"trend": "RED"}, "4h": {"trend": "RED"}, "1h": {"trend": "RED"}}
MIXED_QQE = {"daily": {"trend": "RED"}, "4h": {"trend": "GREEN"}, "1h": {"trend": "RED"}}


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


def _verdict_for(structure, qqe, bmsb, order_blocks, price: float = 100.0):
    """Run the same direction → levels → verdict path the service uses."""
    direction = _determine_trade_direction(structure, qqe, bmsb)
    smc = {"order_blocks": order_blocks}
    levels = (
        _extract_price_levels(
            {"daily": _daily_at(price)}, smc, direction=direction, require_actionable_zone=True
        )
        if direction
        else {}
    )
    return build_verdict(
        direction=direction,
        entry_actionable=bool(levels.get("entry_is_actionable")),
        structure_results=structure,
        qqe_signals=qqe,
        bmsb_data=bmsb,
        price_levels=levels,
        order_blocks=order_blocks,
    )


# ── Scenario 1: fully aligned bull with nearby demand → READY LONG ──────


def test_bull_aligned_with_nearby_zone_is_ready_long():
    verdict = _verdict_for(
        BULL_STRUCTURE, GREEN_QQE, {"regime": "bull"},
        [{"type": "Bullish", "zone": (98.0, 99.0)}],
    )

    assert verdict["state"] == ScanVerdict.READY_LONG.value
    assert verdict["bias"] == "LONG"
    assert verdict["actionable"] is True
    assert verdict["blockers"] == []
    assert all(g["passed"] for g in verdict["gates"])


# ── Scenario 2: fully aligned bear with nearby supply → READY SHORT ─────


def test_bear_aligned_with_nearby_zone_is_ready_short():
    verdict = _verdict_for(
        BEAR_STRUCTURE, RED_QQE, {"regime": "bear"},
        [{"type": "Bearish", "zone": (101.0, 102.0)}],
    )

    assert verdict["state"] == ScanVerdict.READY_SHORT.value
    assert verdict["bias"] == "SHORT"
    assert verdict["actionable"] is True
    assert verdict["blockers"] == []


# ── Scenario 3: mixed tape → NO TRADE with a stated, unconfirmed lean ───


def test_mixed_signals_are_no_trade_with_bearish_lean():
    verdict = _verdict_for(
        MIXED_STRUCTURE, MIXED_QQE, {"regime": "bear"},
        [{"type": "Bullish", "zone": (98.0, 99.0)}],
    )

    assert verdict["state"] == ScanVerdict.NO_TRADE.value
    assert verdict["display"] == "NO TRADE TODAY"
    assert verdict["actionable"] is False
    # regime bear + LH + LL + RED + RED = 5/7 votes → stated lean, not a trade
    assert verdict["bias"] == "SHORT"
    assert "do not front-run" in verdict["reasoning"]
    assert any(not g["passed"] for g in verdict["gates"])


# ── Scenario 4: aligned context but only a distant zone → WATCH ─────────


def test_distant_zone_is_watch_not_entry():
    verdict = _verdict_for(
        BULL_STRUCTURE, GREEN_QQE, {"regime": "bull"},
        [{"type": "Bullish", "zone": (80.0, 81.0)}],
    )

    assert verdict["state"] == ScanVerdict.WATCH.value
    assert verdict["bias"] == "LONG"
    assert verdict["actionable"] is False
    zone_gate = next(g for g in verdict["gates"] if g["id"] == "zone")
    assert zone_gate["passed"] is False
    assert any("zone" in b.lower() for b in verdict["blockers"])


# ── Scenario 5: missing BMSB data → NO TRADE, regime gate explains ──────


def test_missing_bmsb_is_no_trade_with_unknown_regime():
    verdict = _verdict_for(
        BULL_STRUCTURE, GREEN_QQE, None,
        [{"type": "Bullish", "zone": (98.0, 99.0)}],
    )

    assert verdict["state"] == ScanVerdict.NO_TRADE.value
    regime_gate = next(g for g in verdict["gates"] if g["id"] == "regime")
    assert regime_gate["passed"] is False
    assert "unknown" in regime_gate["detail"]


# ── Scenario 6: 2R path blocked by opposing supply → WATCH, not READY ───


def test_supply_before_2r_target_demotes_ready_to_watch():
    price_levels = {
        "current_price": 100.0,
        "entry_zone_low": 98.0,
        "entry_zone_high": 99.0,
        "entry_is_actionable": True,
        "stop_loss": 95.0,
        "take_profit_1": 101.0,
        "take_profit_2": 104.0,
    }
    verdict = build_verdict(
        direction="LONG",
        entry_actionable=True,
        structure_results=BULL_STRUCTURE,
        qqe_signals=GREEN_QQE,
        bmsb_data={"regime": "bull"},
        price_levels=price_levels,
        order_blocks=[
            {"type": "Bullish", "zone": (98.0, 99.0)},
            {"type": "Bearish", "zone": (102.0, 103.0)},
        ],
    )

    assert verdict["state"] == ScanVerdict.WATCH.value
    risk_gate = next(g for g in verdict["gates"] if g["id"] == "risk")
    assert risk_gate["passed"] is False
    assert "insufficient room" in risk_gate["detail"]


# ── Bias derivation unit checks ─────────────────────────────────────────


def test_bias_requires_supermajority():
    # 4 long votes vs 3 short votes → below the 5/7 threshold → NEUTRAL
    bias = derive_bias(
        {"weekly": "HH", "daily": "HH", "4h": "LL"},
        {"daily": "GREEN", "4h": "GREEN", "1h": "RED"},
        "bear",
    )
    assert bias is Bias.NEUTRAL


def test_bias_supermajority_reports_lean():
    bias = derive_bias(
        {"weekly": "LH", "daily": "LL", "4h": "LL"},
        {"daily": "RED", "4h": "GREEN", "1h": "RED"},
        "bear",
    )
    assert bias is Bias.SHORT


# ── Zone metadata: detection-time facts agree with the selection gate ───


ZONE_META_KEYS = (
    "timeframe", "age_bars", "age_days", "distance_pct",
    "direction_match", "actionable", "reason",
)


def _four_h_at(price: float = 100.0, bars: int = 12) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=bars, freq="4h")
    return pd.DataFrame(
        {
            "Open": [price] * bars,
            "High": [price + 0.5] * bars,
            "Low": [price - 0.5] * bars,
            "Close": [price] * bars,
        },
        index=index,
    )


def test_annotated_nearby_zone_metadata_agrees_with_ready_long():
    df_4h = _four_h_at(100.0)
    zones = smc_module.annotate_zones(
        [{"type": "Bullish", "zone": (98.0, 99.0), "index": df_4h.index[4]}], df_4h
    )
    verdict = _verdict_for(BULL_STRUCTURE, GREEN_QQE, {"regime": "bull"}, zones)

    z = zones[0]
    assert z["timeframe"] == "4h"
    assert z["age_bars"] == 7
    assert z["age_days"] == pytest.approx(7 * 4 / 24, abs=0.01)
    assert z["distance_pct"] == pytest.approx(-1.0, abs=1e-6)
    assert z["direction_match"] == "bullish"
    assert z["actionable"] is True
    # the selection-time gate agrees, and the additive keys did not disturb
    # the verdict path
    assert verdict["state"] == ScanVerdict.READY_LONG.value
    zone_gate = next(g for g in verdict["gates"] if g["id"] == "zone")
    assert zone_gate["passed"] is True


def test_annotated_distant_zone_metadata_agrees_with_watch():
    df_4h = _four_h_at(100.0)
    zones = smc_module.annotate_zones(
        [{"type": "Bullish", "zone": (80.0, 81.0), "index": df_4h.index[0]}], df_4h
    )
    verdict = _verdict_for(BULL_STRUCTURE, GREEN_QQE, {"regime": "bull"}, zones)

    z = zones[0]
    assert z["actionable"] is False
    assert z["distance_pct"] == pytest.approx(-19.0, abs=1e-6)
    assert "beyond" in z["reason"]
    assert verdict["state"] == ScanVerdict.WATCH.value
    assert verdict["actionable"] is False


# ── Normalizers surface zone metadata to the UI payload additively ──────


def test_normalizers_surface_zone_metadata_additively():
    df_4h = _four_h_at(100.0)
    obs = smc_module.annotate_zones(
        [{"type": "Bullish", "zone": (98.0, 99.0), "index": df_4h.index[4]}], df_4h
    )
    fvgs = smc_module.annotate_zones(
        [{"type": "Bearish", "zone": (101.0, 102.0), "index": df_4h.index[6]}], df_4h
    )

    ob_row = _normalize_obs(obs)[0]
    # pre-existing normalized keys unchanged
    assert ob_row["price_low"] == 98.0 and ob_row["price_high"] == 99.0
    assert ob_row["type"] == "Bullish"
    for key in ZONE_META_KEYS:
        assert key in ob_row
    assert ob_row["actionable"] is True
    assert ob_row["age_bars"] == 7
    assert ob_row["direction_match"] == "bullish"

    fvg_row = _normalize_fvgs(fvgs)[0]
    assert fvg_row["price_low"] == 101.0 and fvg_row["price_high"] == 102.0
    for key in ZONE_META_KEYS:
        assert key in fvg_row
    assert fvg_row["direction_match"] == "bearish"
    assert fvg_row["actionable"] is True  # 1% above spot — valid short pullback
    assert fvg_row["distance_pct"] == pytest.approx(1.0, abs=1e-6)


def test_normalizers_tolerate_unannotated_zones():
    # cached pre-metadata payloads must still normalize; new keys default None
    ob_row = _normalize_obs([{"type": "Bullish", "zone": (98.0, 99.0)}])[0]
    assert ob_row["price_low"] == 98.0 and ob_row["price_high"] == 99.0
    for key in ZONE_META_KEYS:
        assert ob_row[key] is None
    fvg_row = _normalize_fvgs([{"type": "Bearish", "zone": (101.0, 102.0)}])[0]
    for key in ZONE_META_KEYS:
        assert fvg_row[key] is None
