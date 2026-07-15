"""Contract tests for the read-only desktop position-intelligence service."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.desktop_position_service import build_desktop_position_intelligence


def _now() -> datetime:
    return datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc)


def _position(symbol: str, **overrides: object) -> dict:
    position = {
        "symbol": symbol,
        "exchange": "mexc",
        "side": "LONG",
        "size": 2.0,
        "contract_size": 1.0,
        "entry_price": 100.0,
        "mark_price": 105.0,
        "pnl": 10.0,
        "unrealizedPnl": None,
        "margin": 50.0,
        "leverage": 5.0,
        "liquidation_price": 75.0,
    }
    position.update(overrides)
    return position


def _scan() -> dict:
    return {
        "structure": {
            "weekly": {
                "label": "HL",
                "swings": [
                    {"type": "low", "price": 80.0, "index": 3},
                    {"type": "high", "price": 128.0, "index": 4},
                ],
            },
            "daily": {
                "label": "HH",
                "swings": [
                    {"type": "low", "price": 94.0, "index": 7},
                    {"type": "high", "price": 118.0, "index": 8},
                    {"type": "low", "price": 101.0, "index": 9},
                    {"type": "high", "price": 111.0, "index": 10},
                ],
            },
            "4h": {
                "label": "HL",
                "swings": [
                    {"type": "low", "price": 102.0, "index": 11},
                    {"type": "high", "price": 109.0, "index": 12},
                ],
            },
            "1h": {
                "label": "HL",
                "swings": [
                    {"type": "low", "price": 103.0, "index": 21},
                    {"type": "high", "price": 107.0, "index": 22},
                ],
            },
        }
    }


def _build(**kwargs: object) -> dict:
    defaults = {
        "exchange": "mexc",
        "now": _now(),
        "portfolio_last_refreshed": _now() - timedelta(seconds=30),
        "mark_price_last_refreshed": _now() - timedelta(seconds=30),
    }
    defaults.update(kwargs)
    return build_desktop_position_intelligence(**defaults)


def test_selects_requested_open_position_and_defaults_by_absolute_pnl() -> None:
    positions = [
        _position("ETHUSDT", pnl=-25.0),
        _position("BTCUSDT", pnl=12.0),
        _position("ADAUSDT", pnl=-25.0),
    ]

    selected = _build(positions=positions, selected_symbol="BTCUSDT")
    assert selected["schema_version"] == 1
    assert selected["position"]["symbol"] == "BTCUSDT"
    assert selected["selection_reason"] == "user_selected"

    defaulted = _build(positions=positions, selected_symbol="SOLUSDT")
    assert defaulted["position"]["symbol"] == "ADAUSDT"
    assert defaulted["selection_reason"] == "selected_position_closed_defaulted"

    no_selection = _build(positions=positions)
    assert no_selection["position"]["symbol"] == "ADAUSDT"
    assert no_selection["selection_reason"] == "no_user_selection_defaulted"


def test_no_open_positions_returns_null_position_and_safe_contract_shell() -> None:
    result = _build(positions=[])

    assert result["schema_version"] == 1
    assert result["position"] is None
    assert result["selection_reason"] == "no_open_positions"
    assert result["privacy"] == {"hide_amounts_available": True, "redaction_supported": True}
    assert result["source"]["stale_status"] == "fresh"


@pytest.mark.parametrize(
    ("side", "entry", "mark", "expected_pnl"),
    [("LONG", 100.0, 110.0, 15.0), ("SHORT", 100.0, 90.0, 15.0)],
)
def test_computes_mexc_contract_pnl_with_contract_size_for_long_and_short(
    side: str,
    entry: float,
    mark: float,
    expected_pnl: float,
) -> None:
    result = _build(
        positions=[
            _position(
                "BTCUSDT",
                side=side,
                entry_price=entry,
                mark_price=mark,
                size=3.0,
                contract_size=0.5,
                pnl=None,
                unrealizedPnl=None,
                margin=30.0,
            )
        ]
    )

    position = result["position"]
    assert position["size_contracts"] == 3.0
    assert position["contract_size"] == 0.5
    assert position["pnl"] == expected_pnl
    assert position["pnl_percent"] == 50.0
    assert position["pnl_formula"] == "computed_contracts_contract_size"
    assert "margin_missing_for_pnl_percent" not in result["errors"]


def test_margin_missing_or_zero_sets_zero_percent_and_error_code() -> None:
    result = _build(
        positions=[
            _position(
                "BTCUSDT",
                entry_price=100.0,
                mark_price=110.0,
                size=3.0,
                contract_size=0.5,
                pnl=None,
                unrealizedPnl=None,
                margin=0.0,
            )
        ]
    )

    assert result["position"]["pnl"] == 15.0
    assert result["position"]["pnl_percent"] == 0.0
    assert "margin_missing_for_pnl_percent" in result["errors"]


def test_extracts_nearest_htf_and_ltf_smc_support_resistance_with_provenance() -> None:
    result = _build(positions=[_position("BTCUSDT", mark_price=105.0)], scans_by_symbol={"BTCUSDT": _scan()})

    htf = result["position"]["htf_sr"]
    assert htf["timeframes"] == ["Daily", "Weekly"]
    assert htf["support"]["price"] == 101.0
    assert htf["support"] == {
        "price": 101.0,
        "distance_pct": pytest.approx(-3.8095238),
        "method": "smc_swing",
        "timeframe": "Daily",
        "swing_type": "swing_low",
        "swing_index": 9,
    }
    assert htf["resistance"]["price"] == 111.0
    assert htf["resistance"]["distance_pct"] == pytest.approx(5.7142857)
    assert htf["resistance"]["timeframe"] == "Daily"
    assert htf["structure_label"] == "HH"
    assert htf["confidence"] == "HIGH"

    ltf = result["position"]["ltf_sr"]
    assert ltf["timeframes"] == ["1H", "4H"]
    assert ltf["support"]["price"] == 103.0
    assert ltf["support"]["distance_pct"] == pytest.approx(-1.9047619)
    assert ltf["support"]["timeframe"] == "1H"
    assert ltf["resistance"]["price"] == 107.0
    assert ltf["resistance"]["distance_pct"] == pytest.approx(1.9047619)
    assert ltf["resistance"]["timeframe"] == "1H"
    assert ltf["confidence"] == "HIGH"


def test_missing_or_insufficient_scan_marks_sr_unavailable_and_advisory_wait() -> None:
    result = _build(
        positions=[_position("BTCUSDT")],
        scans_by_symbol={"BTCUSDT": {"structure": {"daily": {"label": "Insufficient data", "swings": []}}}},
        dca_recommendations_by_symbol={"BTCUSDT": {"recommendation": "HOLD", "reason": "Clean hold"}},
    )

    assert result["position"]["htf_sr"]["confidence"] == "UNAVAILABLE"
    assert result["position"]["htf_sr"]["support"] is None
    assert result["position"]["ltf_sr"]["confidence"] == "UNAVAILABLE"
    assert result["position"]["advisory"]["action"] == "WAIT"
    assert result["position"]["advisory"]["source"] == "combined"


def test_advisory_maps_only_safe_actions_with_conservative_conflict_ordering() -> None:
    add_result = _build(
        positions=[_position("BTCUSDT")],
        scans_by_symbol={"BTCUSDT": _scan()},
        dca_recommendations_by_symbol={"BTCUSDT": {"recommendation": "ADD", "reason": "Add now"}},
    )
    assert add_result["position"]["advisory"]["action"] == "WAIT"
    assert "Add now" not in add_result["position"]["advisory"]["reason"]

    conflict_result = _build(
        positions=[_position("BTCUSDT")],
        scans_by_symbol={"BTCUSDT": _scan()},
        dca_recommendations_by_symbol={"BTCUSDT": {"recommendation": "HOLD", "reason": "Hold"}},
        position_alerts_by_symbol={
            "BTCUSDT": {
                "max_severity": "WARNING",
                "alerts": [{"severity": "WARNING", "type": "STRUCTURE", "message": "conflict"}],
            }
        },
    )
    assert conflict_result["position"]["advisory"]["action"] == "REDUCE"
    assert conflict_result["position"]["advisory"]["severity"] == "WARNING"
    assert conflict_result["position"]["advisory"]["source"] == "combined"

    close_result = _build(
        positions=[_position("BTCUSDT")],
        scans_by_symbol={"BTCUSDT": _scan()},
        dca_recommendations_by_symbol={"BTCUSDT": {"recommendation": "REDUCE", "reason": "Reduce"}},
        position_alerts_by_symbol={
            "BTCUSDT": {
                "max_severity": "DANGER",
                "alerts": [{"severity": "DANGER", "type": "LIQ_DISTANCE", "message": "danger"}],
            }
        },
    )
    assert close_result["position"]["advisory"]["action"] == "CLOSE"
    assert close_result["position"]["advisory"]["severity"] == "DANGER"


def test_source_freshness_and_critical_stale_masks_advisory_reason_without_refresh_side_effects() -> None:
    result = _build(
        positions=[_position("BTCUSDT")],
        scans_by_symbol={"BTCUSDT": _scan()},
        dca_recommendations_by_symbol={"BTCUSDT": {"recommendation": "CLOSE", "reason": "Close now"}},
        mark_price_last_refreshed=_now() - timedelta(seconds=901),
    )

    assert result["source"]["pnl_age_seconds"] == 901
    assert result["source"]["stale_status"] == "critical_stale"
    assert result["position"]["advisory"]["action"] == "CLOSE"
    assert result["position"]["advisory"]["reason"] == "Advisory: Open Miraj to refresh before acting"
    assert result["source"]["refresh_executed"] is False
