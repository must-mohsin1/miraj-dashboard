"""
Tests for indicators module — RSI, BB, EMAs, EMA Ribbon, BMSB, Cross.
"""
import numpy as np
import pandas as pd
import pytest

from mirai_core import indicators


class TestRSI:
    """Wilder's RSI computation."""

    def test_rsi_values_in_range(self):
        """RSI values are always between 0 and 100."""
        close = pd.Series(np.cumsum(np.random.randn(200)) + 100)
        rsi = indicators.wilder_rsi(close)
        valid = rsi.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_rsi_constant_series(self):
        """RSI of a constant series should be 50 (after warmup)."""
        close = pd.Series(np.full(100, 100.0))
        rsi = indicators.wilder_rsi(close)
        last_valid = rsi.dropna()
        if len(last_valid) > 0:
            # After enough bars, RSI converges to 50 for a flat series
            assert abs(last_valid.iloc[-1] - 50.0) < 1.0


class TestBollingerBands:
    """Bollinger Bands computation."""

    def test_upper_greater_than_lower(self):
        """Upper band is always above the lower band (after warmup)."""
        close = pd.Series(np.cumsum(np.random.randn(200)) + 100)
        bb = indicators.compute_bollinger_bands(close)
        valid = bb["upper"].dropna()
        assert (valid >= bb["lower"].dropna()).all()

    def test_middle_is_sma(self):
        """Middle band equals SMA of close."""
        close = pd.Series(np.cumsum(np.random.randn(200)) + 100)
        bb = indicators.compute_bollinger_bands(close, period=20)
        expected_sma = close.rolling(20).mean()
        pd.testing.assert_series_equal(
            bb["middle"].dropna(), expected_sma.dropna(), check_names=False
        )


class TestEMAs:
    """Exponential Moving Averages."""

    def test_emas_computed(self):
        """EMAs for given spans are computed."""
        close = pd.Series(np.cumsum(np.random.randn(200)) + 100)
        emas = indicators.compute_emas(close, spans=[20, 50, 200])
        assert 20 in emas
        assert 50 in emas
        assert 200 in emas
        assert len(emas[20]) == len(close)


class TestCrossDetection:
    """Golden / Death Cross detection."""

    def test_golden_cross_generated(self):
        """Golden cross detected when fast EMA crosses above slow EMA in lookback."""
        # 100 points: flat at 100 for 98 bars, then abrupt rise to guarantee
        # a crossover within the last `lookback=3` positions.
        close = pd.Series([100.0] * 98 + [110.0, 150.0])
        cross = indicators.detect_golden_death_cross(close, fast=10, slow=20)
        assert cross == "golden_cross"

    def test_death_cross_generated(self):
        """Death cross detected when fast EMA crosses below slow EMA in lookback."""
        # 100 points: flat at 100 for 98 bars, then abrupt fall to guarantee
        # a crossover within the last `lookback=3` positions.
        close = pd.Series([100.0] * 98 + [90.0, 50.0])
        cross = indicators.detect_golden_death_cross(close, fast=10, slow=20)
        assert cross == "death_cross"


class TestBullMarketSupportBand:
    """Bull Market Support Band."""

    def test_bmsb_returns_dict(self):
        """BMSB returns dict with sma20 and ema21."""
        close = pd.Series(np.cumsum(np.random.randn(200)) + 100)
        band = indicators.bull_market_support_band(close)
        assert "sma20" in band
        assert "ema21" in band


class TestComputeAll:
    """compute_all returns all indicators."""

    def test_compute_all_keys(self):
        """Compute all returns expected keys."""
        np.random.seed(42)
        idx = pd.date_range("2024-01-01", periods=200, freq="D")
        df = pd.DataFrame(
            {
                "Open": np.cumsum(np.random.randn(200)) + 100,
                "High": np.cumsum(np.random.randn(200)) + 102,
                "Low": np.cumsum(np.random.randn(200)) + 98,
                "Close": np.cumsum(np.random.randn(200)) + 100,
                "Volume": np.random.randint(1000, 10000, 200),
            },
            index=idx,
        )
        result = indicators.compute_all(df)
        expected_keys = {
            "rsi", "bb", "emas", "ema_ribbon",
            "golden_death_cross", "bmsb", "bb_squeeze",
        }
        assert expected_keys.issubset(result.keys())
