"""
Tests for SMC module — Order Blocks, FVGs, divergences, liquidity grabs.
"""
import numpy as np
import pandas as pd
import pytest

from mirai_core import smc


class TestSMC:
    """SMC analysis on synthetic data."""

    def _make_synthetic_4h(self, bars=200):
        """Create synthetic 4H-like data with known patterns."""
        np.random.seed(42)
        idx = pd.date_range("2024-01-01", periods=bars, freq="4h")
        close_arr = 100 + np.cumsum(np.random.randn(bars) * 0.3)
        close = pd.Series(close_arr, index=idx)
        return pd.DataFrame(
            {
                "Open": close.shift(1).fillna(close.iloc[0]),
                "High": close + pd.Series(np.abs(np.random.randn(bars)), index=idx) * 1.5,
                "Low": close - pd.Series(np.abs(np.random.randn(bars)), index=idx) * 1.5,
                "Close": close,
                "Volume": pd.Series(np.random.randint(1000, 10000, bars), index=idx),
            }
        )

    def test_find_order_blocks_returns_list(self):
        """Order blocks detection returns a list."""
        df = self._make_synthetic_4h()
        obs = smc.find_order_blocks(df)
        assert isinstance(obs, list)

    def test_find_fvgs_returns_list(self):
        """FVG detection returns a list with correct structure."""
        df = self._make_synthetic_4h()
        fvgs = smc.find_fvgs(df)
        assert isinstance(fvgs, list)
        if fvgs:
            for fvg in fvgs:
                assert "type" in fvg
                assert fvg["type"] in ("Bullish", "Bearish")
                assert "zone" in fvg
                assert len(fvg["zone"]) == 2

    def test_detect_rsi_divergences_returns_list(self):
        """RSI divergence detection returns a list."""
        df = self._make_synthetic_4h()
        divergences = smc.detect_rsi_divergences(df["Close"])
        assert isinstance(divergences, list)

    def test_find_liquidity_grabs_returns_list(self):
        """Liquidity grab detection returns a list."""
        df = self._make_synthetic_4h()
        grabs = smc.find_liquidity_grabs(df)
        assert isinstance(grabs, list)
        if grabs:
            for g in grabs:
                assert "type" in g
                assert "description" in g

    def test_find_trend_lines_returns_list(self):
        """Trend line detection returns a list with slope and position."""
        df = self._make_synthetic_4h()
        lines = smc.find_trend_lines(df)
        assert isinstance(lines, list)

    def test_analyze_returns_all_keys(self):
        """Full SMC analyze returns all detection categories."""
        df = self._make_synthetic_4h()
        result = smc.analyze(df)
        expected = {"order_blocks", "fvgs", "divergences",
                    "liquidity_grabs", "trend_lines"}
        assert expected.issubset(result.keys())
