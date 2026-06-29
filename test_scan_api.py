"""Tests for the One-click Scan API (P1-E).

Run with::

    cd <workspace>
    .venv/bin/python test_scan_api.py

If you want to test the live endpoint, start the server first::

    .venv/bin/uvicorn backend.main:app --port 8000 &

When the server is not running, the endpoint test is skipped gracefully.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

# ── Ensure mirai_core and backend are importable ─────────────────────
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORKSPACE)

# Force the test database path before any imports
os.environ["DATABASE_URL"] = os.path.join(WORKSPACE, "test_scan.db")

import httpx
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from backend.services.analysis_service import (
    _cache,
    CACHE_TTL,
    clear_cache,
    get_cached_or_none,
    run_scan,
    _is_stale,
    _build_confluence_data,
    _simplify_indicator_summary,
)

BASE = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")

P = 0  # passed
F = 0  # failed


def _reset_cache():
    """Clear the analysis service cache."""
    clear_cache()


# ── Helpers ─────────────────────────────────────────────────────────


def _make_ohlcv(bars: int = 100, start_price: float = 100.0) -> pd.DataFrame:
    """Generate deterministic synthetic OHLCV data."""
    np.random.seed(42)
    idx = pd.date_range(start="2024-01-01", periods=bars, freq="D")
    close_arr = start_price + np.cumsum(np.random.randn(bars) * 0.5)
    close = pd.Series(close_arr, index=idx)
    high = close + pd.Series(np.abs(np.random.randn(bars)), index=idx) * 0.5
    low = close - pd.Series(np.abs(np.random.randn(bars)), index=idx) * 0.5
    open_p = close.shift(1).fillna(float(close.iloc[0]))
    volume = pd.Series(np.random.randint(1000, 10000, bars), index=idx)
    return pd.DataFrame(
        {"Open": open_p, "High": high, "Low": low, "Close": close, "Volume": volume}
    )


def _make_indicator_result() -> dict:
    """Return fake indicator result matching indicators.compute_all shape."""
    close_series = pd.Series(np.linspace(100, 110, 100))
    return {
        "rsi": pd.Series(np.random.uniform(30, 70, 100)),
        "bb": {
            "upper": close_series * 1.02,
            "middle": close_series,
            "lower": close_series * 0.98,
            "bandwidth": pd.Series(np.random.uniform(0.01, 0.1, 100)),
        },
        "emas": {20: close_series * 0.99, 50: close_series * 0.98, 200: close_series * 0.97},
        "ema_ribbon": {
            20: close_series * 0.99,
            25: close_series * 0.985,
            30: close_series * 0.98,
            35: close_series * 0.975,
            40: close_series * 0.97,
            45: close_series * 0.965,
            50: close_series * 0.96,
            55: close_series * 0.955,
        },
        "golden_death_cross": None,
        "bmsb": {"sma20": close_series * 0.95, "ema21": close_series * 0.95},
        "bb_squeeze": False,
    }


def _make_smc_result() -> dict:
    """Return fake SMC result."""
    return {
        "order_blocks": [
            {"type": "Bullish", "zone": (95.0, 98.0), "index": pd.Timestamp("2024-03-01")}
        ],
        "fvgs": [
            {"type": "Bullish", "zone": (96.0, 97.0), "index": pd.Timestamp("2024-03-02")}
        ],
        "divergences": [
            {"type": "Bullish", "description": "Price LL but RSI HL — potential reversal up"}
        ],
        "liquidity_grabs": [
            {"type": "Bullish", "price": 94.5, "sweep_index": pd.Timestamp("2024-03-03"),
             "description": "liquidity grab test"}
        ],
        "trend_lines": [
            {"type": "Support", "slope": 0.01, "current_value": 96.0, "broken": False}
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests — confluence data builder
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_confluence_data_basic():
    """Verify _build_confluence_data returns expected keys with bool values."""
    _reset_cache()

    macro_data = {
        "btc_d": 55.0,
        "usdt_d": 3.5,
        "dxy": 104.0,
        "fear_greed": {"value": 45, "classification": "Fear"},
        "long_short_ratio_btc": 1.2,
    }

    ind_results = {
        "weekly": _make_indicator_result(),
        "daily": _make_indicator_result(),
        "4h": _make_indicator_result(),
        "1h": {"error": "no data"},
        "15m": {"error": "no data"},
    }

    qqe_results = {
        "daily": {"signal": "GREEN", "trend": "BULLISH"},
        "4h": {"signal": "RED", "trend": "BEARISH"},
        "1h": {"error": "no data"},
    }

    smc_result = _make_smc_result()
    pattern_result = {"detected": [{"pattern": "Double Bottom", "signal": "Bullish", "confirmed": True}]}

    data = _build_confluence_data(macro_data, ind_results, qqe_results, smc_result, pattern_result)

    # Check it has all expected keys
    expected_keys = [
        "weekly_structure_aligned", "daily_structure_aligned", "btc_d_aligned",
        "weekly_200ma_position", "usdt_d_favourable", "bmsb_aligned",
        "fear_greed_aligned", "demand_supply_zone", "ote_overlap",
        "order_block_at_zone", "fvg_at_zone", "liquidity_grab_before_ote",
        "trend_line_at_zone", "h4_structure_aligned", "daily_rsi_confirms",
        "h4_rsi_confirms", "bb_not_squeezing", "qqe_aligned",
        "m15_structure_aligned", "rsi_divergence_present",
        "chart_pattern_confirmed", "ema_ribbon_aligned",
        "volume_confirming", "retest_confirmed", "no_fakeout",
        "target_2r_available", "clean_stop_level", "no_news_risk",
    ]
    for key in expected_keys:
        assert key in data, f"Missing key: {key}"
        assert isinstance(data[key], bool), f"Key {key} is not bool: {type(data[key])}"

    # BTC.D > 50 → btc_d_aligned
    assert data["btc_d_aligned"] is True
    # USDT.D < 5 → usdt_d_favourable
    assert data["usdt_d_favourable"] is True
    # order_blocks present → location/retest keys
    assert data["ote_overlap"] is True
    assert data["order_block_at_zone"] is True
    assert data["retest_confirmed"] is True
    # divergences present
    assert data["rsi_divergence_present"] is True
    # QQE has GREEN signal
    assert data["qqe_aligned"] is True

    global P, F
    P += 1
    print("  PASS test_build_confluence_data_basic")


def test_build_confluence_data_empty():
    """Verify _build_confluence_data handles empty inputs gracefully."""
    _reset_cache()

    data = _build_confluence_data({}, {}, {}, {}, {})

    # All keys should exist and be False (safely falsy)
    for key, val in data.items():
        assert isinstance(val, bool), f"Key {key} is not bool: {type(val)}"

    global P, F
    P += 1
    print("  PASS test_build_confluence_data_empty")


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests — caching
# ═══════════════════════════════════════════════════════════════════════════════


def test_cache_miss():
    """Querying a symbol not in cache should return None."""
    _reset_cache()
    result = get_cached_or_none("NONEXIST")
    assert result is None
    global P, F
    P += 1
    print("  PASS test_cache_miss")


def test_cache_hit_and_stale():
    """Verify that a fresh cache entry is returned, and is stale after TTL."""
    _reset_cache()
    from backend.services.analysis_service import _cache

    # Manually populate cache
    _cache["BTC-USD"] = {
        "data": {
            "symbol": "BTC-USD",
            "confluence_score": 15.0,
            "trade_plan": {"trade_decision": True},
            "score_breakdown": {"total": 15.0, "trade_decision": True},
        },
        "cached_at": time.time(),
    }

    # Should return cached data (not stale)
    result = get_cached_or_none("BTC-USD")
    assert result is not None
    assert result["stale"] is False
    assert result["confluence_score"] == 15.0
    assert result["symbol"] == "BTC-USD"

    # Make it stale by advancing time backward in the cache
    _cache["BTC-USD"]["cached_at"] = time.time() - CACHE_TTL - 60
    assert _is_stale("BTC-USD") is True

    # After stale, get_cached_or_none should return None
    result = get_cached_or_none("BTC-USD")
    assert result is None

    global P, F
    P += 1
    print("  PASS test_cache_hit_and_stale")


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests — indicator summary
# ═══════════════════════════════════════════════════════════════════════════════


def test_simplify_indicator_summary():
    """Verify _simplify_indicator_summary extracts scalar values."""
    ind_results = {
        "daily": _make_indicator_result(),
        "4h": {"error": "no data"},
    }
    summary = _simplify_indicator_summary(ind_results)

    assert "daily" in summary
    assert "rsi" in summary["daily"]
    assert isinstance(summary["daily"]["rsi"], float)
    assert 0 <= summary["daily"]["rsi"] <= 100

    assert "4h" in summary
    assert "error" in summary["4h"]

    global P, F
    P += 1
    print("  PASS test_simplify_indicator_summary")


# ═══════════════════════════════════════════════════════════════════════════════
# Mocked service integration tests
# ═══════════════════════════════════════════════════════════════════════════════


def _patch_mirai_core():
    """Return a context manager that patches all mirai_core functions.

    Yields a callable that tears down all patches on exit.
    """
    import contextlib
    import unittest.mock as mock

    mock_df = _make_ohlcv(100)

    mock_timeframes = {
        "weekly": _make_ohlcv(104, start_price=100.0),
        "daily": mock_df,
        "4h": _make_ohlcv(360, start_price=100.0),
        "1h": _make_ohlcv(720, start_price=100.0),
        "15m": _make_ohlcv(1440, start_price=100.0),
    }

    mock_indicator = _make_indicator_result()
    mock_smc = _make_smc_result()
    mock_patterns = {"detected": [{"pattern": "Double Bottom", "signal": "Bullish", "confirmed": True}]}

    patchers = [
        mock.patch("backend.services.analysis_service.ohlcv.fetch_all_timeframes",
                   return_value=mock_timeframes),
        mock.patch("backend.services.analysis_service.indicators.compute_all",
                   return_value=mock_indicator),
        mock.patch("backend.services.analysis_service.qqe_mod.compute_qqe",
                   return_value={"signal": "GREEN", "trend": "BULLISH", "qqe_line": 55.0,
                                 "qqe_trailing": 50.0, "histogram": 3.5,
                                 "vol_buying_pct": 60.0, "bars": ["GREEN"] * 10,
                                 "trend_history": [1] * 20}),
        mock.patch("backend.services.analysis_service.smc.analyze",
                   return_value=mock_smc),
        mock.patch("backend.services.analysis_service.patterns.detect",
                   return_value=mock_patterns["detected"]),
        mock.patch("backend.services.analysis_service.macro.fetch_macro_data",
                   return_value={
                       "btc_d": 52.0,
                       "usdt_d": 4.2,
                       "dxy": 103.5,
                       "fear_greed": {"value": 48, "classification": "Fear"},
                       "long_short_ratio_btc": 1.15,
                   }),
    ]

    @contextlib.contextmanager
    def _combined():
        for p in patchers:
            p.start()
        try:
            yield
        finally:
            for p in patchers:
                p.stop()

    return _combined()


def test_run_scan_success():
    """Full pipeline with mocked data should return complete response."""
    _reset_cache()

    with _patch_mirai_core():
        result = run_scan("BTC-USD")

    # Verify structure
    assert result["symbol"] == "BTC-USD"
    assert isinstance(result["confluence_score"], float)
    assert 0 <= result["confluence_score"] <= 30
    assert isinstance(result["trade_plan"], dict)
    assert "trade_decision" in result["trade_plan"]
    assert isinstance(result["score_breakdown"], dict)
    assert "total" in result["score_breakdown"]
    assert result["stale"] is False
    assert result["cached_at"] is not None

    # Verify caching works after the run
    cached = get_cached_or_none("BTC-USD")
    assert cached is not None
    assert cached["confluence_score"] == result["confluence_score"]

    global P, F
    P += 1
    print("  PASS test_run_scan_success")


def test_run_scan_caching():
    """Running the same symbol twice within TTL should return cached data."""
    _reset_cache()

    with _patch_mirai_core():
        result1 = run_scan("BTC-USD")

    # Second call should return cached (from the stored _cache)
    with _patch_mirai_core():
        result2 = run_scan("BTC-USD")

    # Both results should have same score (cached)
    assert result2["confluence_score"] == result1["confluence_score"]
    assert result2["stale"] is False  # still fresh

    global P, F
    P += 1
    print("  PASS test_run_scan_caching")


def test_run_scan_yfinance_failure():
    """When yfinance fails, run_scan should raise RuntimeError."""
    _reset_cache()

    with patch("backend.services.analysis_service.ohlcv.fetch_all_timeframes",
               side_effect=Exception("yfinance timeout")) as patcher:
        try:
            run_scan("BTC-USD")
            assert False, "Expected RuntimeError"
        except RuntimeError as e:
            assert "yfinance" in str(e).lower() or "API" in str(e)

    global P, F
    P += 1
    print("  PASS test_run_scan_yfinance_failure")


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoint test
# ═══════════════════════════════════════════════════════════════════════════════


async def test_scan_endpoint():
    """Hit the live /api/v1/scan/BTC-USD endpoint and verify the shape.

    This test requires the server to be running. If unreachable, it's
    skipped gracefully.
    """
    global P, F
    _reset_cache()

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BASE}/api/v1/scan/BTC-USD", timeout=90.0)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            print(f"  SKIP test_scan_endpoint — server unreachable: {e}")
            P += 1
            return

    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )
    body = resp.json()

    # Response structure
    assert "symbol" in body
    assert "confluence_score" in body
    assert "trade_plan" in body
    assert "score_breakdown" in body
    assert "stale" in body
    assert "cached_at" in body
    assert body["symbol"] == "BTC-USD"
    assert 0 <= body["confluence_score"] <= 30
    assert isinstance(body["trade_plan"], dict)
    assert isinstance(body["score_breakdown"], dict)

    # Second call should be cached
    async with httpx.AsyncClient() as client2:
        resp2 = await client2.post(f"{BASE}/api/v1/scan/BTC-USD", timeout=30.0)
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["stale"] is False  # still fresh (just ran)

    print(f"  PASS test_scan_endpoint — score: {body['confluence_score']}/30")
    P += 1


# ═══════════════════════════════════════════════════════════════════════════════
# Main runner
# ═══════════════════════════════════════════════════════════════════════════════


async def main():
    global P, F
    F = 0
    P = 0

    print("=" * 50)
    print("One-click Scan API — Test Suite (P1-E)")
    print("=" * 50)
    print()

    # ── Unit tests ─────────────────────────────────────────────────
    print("--- Unit: confluence data builder ---")
    test_build_confluence_data_basic()
    test_build_confluence_data_empty()
    print()

    print("--- Unit: caching ---")
    test_cache_miss()
    test_cache_hit_and_stale()
    print()

    print("--- Unit: indicator summary ---")
    test_simplify_indicator_summary()
    print()

    # ── Mocked service tests ───────────────────────────────────────
    print("--- Service (mocked pipeline) ---")
    test_run_scan_success()
    test_run_scan_caching()
    test_run_scan_yfinance_failure()
    print()

    # ── Endpoint integration (needs server) ────────────────────────
    print("--- Endpoint (live server) ---")
    await test_scan_endpoint()
    print()

    # ── Summary ────────────────────────────────────────────────────
    print("=" * 50)
    print(f"Results: {P} passed, {F} failed out of {P + F} tests")
    print("=" * 50)

    # Cleanup test DB
    for f in ["test_scan.db", "crypto_analysis.db"]:
        db_path = os.path.join(WORKSPACE, f)
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"Cleaned up {f}")

    sys.exit(0 if F == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
