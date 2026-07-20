"""Position Desk service — ruling composition and verdict joining."""
import asyncio
import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from backend.services import position_desk_service as desk


def _position(**overrides):
    base = {
        "symbol": "HYPE_USDT",
        "side": "long",
        "size": 10.0,
        "entry_price": 70.0,
        "mark_price": 62.0,
        "pnl": -80.0,
        "pnl_percent": -11.4,
        "leverage": 3.0,
        "liquidation_price": 40.0,
        "margin": 100.0,
        "contract_size": 1.0,
    }
    base.update(overrides)
    return base


def _scan(regime="bull", **overrides):
    scan = {
        "symbol": "HYPE-USD",
        "confluence_score": 8.0,
        "score_breakdown": {"total": 8.0},
        "verdict": {
            "state": "NO_TRADE",
            "bias": "NEUTRAL",
            "next_review": "next 4H candle close",
        },
        "bmsb": {
            "regime": regime,
            "status": "above" if regime == "bull" else "below",
            "sma_20w": 52.67,
            "ema_21w": 54.23,
            "current_price": 62.0,
        },
        "qqe": {},
        "qqe_signals": {},
        "structure": {},
        "smc": {},
        "patterns": {},
        "indicators": {},
        "trade_plan": {},
        "trade_plan_flat": {},
    }
    scan.update(overrides)
    return scan


def test_bear_regime_long_is_counter_regime_reduce():
    row = desk.build_desk_row(_position(), _scan(regime="bear"))

    assert row["alignment"] == "COUNTER_REGIME"
    assert row["recommendation"] == "REDUCE"
    assert row["ruling"] == "Reduce — wrong side of the weekly band."
    assert row["regime"] == "bear"
    assert row["regime_band_low"] == 52.67
    assert row["regime_band_high"] == 54.23
    assert row["verdict"]["state"] == "NO_TRADE"
    assert row["next_review"] == "next 4H candle close"


def test_near_liquidation_rules_close():
    row = desk.build_desk_row(
        _position(mark_price=62.0, liquidation_price=61.5),
        _scan(regime="bull"),
    )

    assert row["recommendation"] == "CLOSE"
    assert row["ruling"] == "Close the position."
    assert row["liq_distance_pct"] == 0.81


def test_missing_scan_is_no_data_manual_review():
    row = desk.build_desk_row(_position(), None)

    assert row["alignment"] == "NO_DATA"
    assert row["ruling"] == "No data — manual review."
    assert row["verdict"] is None
    assert row["scan_symbol"] == "HYPE-USD"


def test_bull_regime_hold_names_the_add_zone():
    scan = _scan(regime="bull", trade_plan={"entry_zone": {"low": 60.42, "high": 61.42}})
    row = desk.build_desk_row(_position(), scan)

    assert row["alignment"] == "ALIGNED"
    assert row["recommendation"] == "HOLD"
    assert "60.42" in row["ruling"] and "61.42" in row["ruling"]


def test_compute_position_desk_joins_scans(monkeypatch):
    scans = [_scan(regime="bear")]

    async def fake_fetch(positions):
        return scans

    monkeypatch.setattr(desk, "fetch_scans_for_positions", fake_fetch)

    rows = asyncio.run(desk.compute_position_desk([_position()]))

    assert len(rows) == 1
    assert rows[0]["symbol"] == "HYPE_USDT"
    assert rows[0]["scan_symbol"] == "HYPE-USD"
    assert rows[0]["alignment"] == "COUNTER_REGIME"
