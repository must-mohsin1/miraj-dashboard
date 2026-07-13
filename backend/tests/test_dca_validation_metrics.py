"""Tests for DCA validation metrics computed from reconstruction output."""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.dca_validation_metrics import compute_dca_validation_metrics


def _add_event(ts: str, symbol: str, level: int, price: float, *, safe: bool = True) -> dict:
    return {
        "timestamp": ts,
        "symbol": symbol,
        "recommendation": "ADD",
        "participates_in_metrics": True,
        "entry_level": level,
        "fill_price": price,
        "raw_price": price,
        "notional": 1000.0,
        "dca_safe": safe,
        "planned_entry_zone": [price * 0.98, price * 1.02],
    }


def _symbol_result(
    symbol: str,
    *,
    net_pnl: float,
    gross_pnl: float | None = None,
    first_scan: str = "2026-01-01T00:00:00",
    last_scan: str = "2026-01-04T00:00:00",
    fill_levels: tuple[int, ...] = (1, 2, 3),
    max_gap_seconds: int = 3600,
) -> dict:
    fills = [
        {
            "level": level,
            "timestamp": f"2026-01-0{level + 1}T00:00:00",
            "fill_price": 100.0 - level,
            "raw_price": 100.0 - level,
            "notional": 1000.0,
        }
        for level in fill_levels
    ]
    events = [
        {"timestamp": first_scan, "symbol": symbol, "recommendation": "HOLD", "participates_in_metrics": False},
        *[
            _add_event(fill["timestamp"], symbol, fill["level"], fill["fill_price"])
            for fill in fills
        ],
        {"timestamp": last_scan, "symbol": symbol, "recommendation": "CLOSE", "participates_in_metrics": True},
    ]
    return {
        "symbol": symbol,
        "status": "metrics_available",
        "scan_count": len(events),
        "first_scan_at": first_scan,
        "last_scan_at": last_scan,
        "max_scan_gap_seconds": max_gap_seconds,
        "events": events,
        "reconstructed_position": {
            "status": "closed",
            "fills": fills,
            "exit_timestamp": last_scan,
            "valuation_timestamp": last_scan,
            "valuation_price": 110.0,
        },
        "pnl": {
            "gross_pnl": gross_pnl if gross_pnl is not None else net_pnl,
            "fees": 1.0,
            "slippage_impact": 1.0,
            "net_pnl": net_pnl,
        },
        "data_quality_warnings": [],
        "skipped_scans": [],
    }


def test_computes_per_symbol_portfolio_and_dca_metrics() -> None:
    reconstruction = {
        "exchange": "binance",
        "symbols": [
            _symbol_result("BTCUSDT", net_pnl=120.0),
            _symbol_result("ETHUSDT", net_pnl=-60.0, gross_pnl=-55.0, fill_levels=(1, 2)),
        ],
    }

    result = compute_dca_validation_metrics(reconstruction)

    btc = result["symbols"][0]
    assert btc["symbol"] == "BTCUSDT"
    assert btc["metrics"]["reconstructed_trade_count"]["value"] == 1
    assert btc["metrics"]["win_rate"]["value"] == pytest.approx(100.0)
    assert btc["metrics"]["total_return"]["value"] == pytest.approx(4.0)
    assert btc["metrics"]["gross_profit"]["value"] == pytest.approx(120.0)
    assert btc["metrics"]["gross_loss"]["value"] == pytest.approx(0.0)
    assert btc["metrics"]["profit_factor"]["value"] is None
    assert btc["metrics"]["profit_factor"]["reason"] == "gross_loss_is_zero"
    assert btc["metrics"]["max_drawdown_absolute"]["value"] == pytest.approx(0.0)
    assert btc["metrics"]["max_drawdown_percent"]["value"] == pytest.approx(0.0)
    assert btc["metrics"]["average_hold_time_hours"]["value"] == pytest.approx(48.0)
    assert btc["metrics"]["exposure_percentage"]["value"] == pytest.approx(100.0)
    assert btc["dca_metrics"]["entry_level_completion_rate"]["value"] == pytest.approx(1.0)
    assert btc["dca_metrics"]["average_entry_price_vs_planned_zone"]["value"]["average_entry_price"] == pytest.approx(98.0)
    assert btc["dca_metrics"]["add_follow_through_rate"]["value"] == pytest.approx(1.0)
    assert btc["dca_metrics"]["dca_safe_flag_accuracy"]["value"] == pytest.approx(1.0)
    assert btc["dca_metrics"]["three_entry_completion_rate"]["value"] == pytest.approx(1.0)

    portfolio = result["portfolio"]["metrics"]
    assert portfolio["reconstructed_trade_count"]["value"] == 2
    assert portfolio["win_rate"]["value"] == pytest.approx(50.0)
    assert portfolio["gross_profit"]["value"] == pytest.approx(120.0)
    assert portfolio["gross_loss"]["value"] == pytest.approx(60.0)
    assert portfolio["profit_factor"]["value"] == pytest.approx(2.0)
    assert portfolio["total_return"]["value"] == pytest.approx(1.2)


def test_returns_null_reasons_for_insufficient_samples() -> None:
    reconstruction = {
        "exchange": "binance",
        "symbols": [
            {
                "symbol": "SOLUSDT",
                "status": "insufficient_history",
                "scan_count": 1,
                "required_minimum_scans": 2,
                "first_scan_at": "2026-01-01T00:00:00",
                "last_scan_at": "2026-01-01T00:00:00",
                "events": [],
                "reconstructed_position": None,
                "pnl": None,
                "skipped_scans": [],
                "data_quality_warnings": [],
            }
        ],
    }

    result = compute_dca_validation_metrics(reconstruction)
    metrics = result["symbols"][0]["metrics"]

    assert metrics["win_rate"] == {"value": None, "reason": "fewer_than_1_reconstructed_trades"}
    assert metrics["profit_factor"] == {"value": None, "reason": "fewer_than_1_reconstructed_trades"}
    assert metrics["sharpe"] == {"value": None, "reason": "fewer_than_2_return_observations"}
    assert metrics["sortino"] == {"value": None, "reason": "fewer_than_2_return_observations"}
    assert result["symbols"][0]["insufficient_reasons"] == ["insufficient_history"]


def test_walk_forward_split_benchmark_unavailable_and_bias_warnings() -> None:
    reconstruction = {
        "exchange": "binance",
        "symbols": [
            _symbol_result("BTCUSDT", net_pnl=100.0, first_scan="2026-01-01T00:00:00", last_scan="2026-01-02T00:00:00"),
            _symbol_result("BTCUSDT", net_pnl=80.0, first_scan="2026-01-03T00:00:00", last_scan="2026-01-04T00:00:00"),
            _symbol_result("BTCUSDT", net_pnl=60.0, first_scan="2026-01-05T00:00:00", last_scan="2026-01-06T00:00:00"),
            _symbol_result("BTCUSDT", net_pnl=-200.0, first_scan="2026-01-07T00:00:00", last_scan="2026-01-10T00:00:00", max_gap_seconds=72 * 3600),
        ],
    }

    result = compute_dca_validation_metrics(reconstruction, split_ratio=0.75)

    symbol = result["symbols"][0]
    assert symbol["walk_forward"]["split_ratio"] == 0.75
    assert symbol["walk_forward"]["in_sample"]["date_range"] == {
        "start": "2026-01-01T00:00:00",
        "end": "2026-01-06T00:00:00",
    }
    assert symbol["walk_forward"]["out_of_sample"]["date_range"] == {
        "start": "2026-01-07T00:00:00",
        "end": "2026-01-10T00:00:00",
    }
    assert symbol["walk_forward"]["in_sample"]["metrics"]["win_rate"]["value"] == pytest.approx(100.0)
    assert symbol["walk_forward"]["out_of_sample"]["metrics"]["win_rate"]["value"] == pytest.approx(0.0)
    assert symbol["buy_and_hold_benchmark"] == {
        "value": None,
        "reason": "benchmark_price_history_unavailable_from_reconstruction",
    }
    assert "scan_gap_over_48_hours" in symbol["warnings"]
    assert "fewer_than_30_reconstructed_recommendation_events" in symbol["warnings"]
    assert "missing_benchmark_data" in symbol["warnings"]
    assert "out_of_sample_underperformed_in_sample" in symbol["warnings"]


def test_rejects_invalid_split_ratio() -> None:
    with pytest.raises(ValueError, match="split_ratio must be greater than 0 and less than 1"):
        compute_dca_validation_metrics({"exchange": "binance", "symbols": []}, split_ratio=1.0)
