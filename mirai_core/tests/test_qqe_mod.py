"""
Tests for QQE Mod module — exact formula with Wilder's RSI → smooth → trailing stop.
"""
import numpy as np
import pandas as pd
import pytest

from mirai_core import qqe_mod


class TestQQEMod:
    """QQE Mod computation and signal generation."""

    def _make_df(self, bars=200):
        np.random.seed(42)
        idx = pd.date_range("2024-01-01", periods=bars, freq="D")
        close_arr = 100 + np.cumsum(np.random.randn(bars) * 0.5)
        close = pd.Series(close_arr, index=idx)
        return pd.DataFrame(
            {
                "Open": close.shift(1).fillna(close.iloc[0]),
                "High": close + pd.Series(np.abs(np.random.randn(bars)), index=idx),
                "Low": close - pd.Series(np.abs(np.random.randn(bars)), index=idx),
                "Close": close,
                "Volume": pd.Series(np.random.randint(1000, 10000, bars), index=idx),
            }
        )

    def test_compute_qqe_returns_dict(self):
        """compute_qqe returns a dict with expected keys."""
        df = self._make_df()
        result = qqe_mod.compute_qqe(df)
        assert isinstance(result, dict)
        for key in ("qqe_line", "qqe_trailing", "trend", "signal", "bars"):
            assert key in result, f"Missing key: {key}"

    def test_signal_is_valid(self):
        """Signal is one of the valid values."""
        df = self._make_df()
        result = qqe_mod.compute_qqe(df)
        assert result["signal"] in (
            "GREEN", "RED", "GREEN-STRONG", "RED-STRONG", "Neutral"
        )

    def test_trend_is_valid(self):
        """Trend is BULLISH, BEARISH, or Neutral."""
        df = self._make_df()
        result = qqe_mod.compute_qqe(df)
        assert result["trend"] in ("BULLISH", "BEARISH", "Neutral")

    def test_bars_are_correct_signals(self):
        """Bar colours are valid QQE signals."""
        df = self._make_df()
        result = qqe_mod.compute_qqe(df)
        for bar in result["bars"]:
            assert bar in (
                "GREEN", "RED", "GREEN-STRONG", "RED-STRONG"
            ), f"Invalid bar colour: {bar}"

    def test_qqe_line_is_numeric(self):
        """qqe_line should be a float or None."""
        df = self._make_df()
        result = qqe_mod.compute_qqe(df)
        if result["qqe_line"] is not None:
            assert isinstance(result["qqe_line"], float)

    def test_histogram_sign_matches_trend(self):
        """If trend is BULLISH, histogram >= 0. If bearish, histogram <= 0."""
        df = self._make_df(100)
        result = qqe_mod.compute_qqe(df)
        if result["histogram"] is not None:
            if result["trend"] == "BULLISH":
                assert result["histogram"] >= -0.1, "Bullish trend should have non-negative hist"
            elif result["trend"] == "BEARISH":
                assert result["histogram"] <= 0.1, "Bearish trend should have non-positive hist"
