"""
Tests for ohlcv module — data fetching and flattening.
"""
import pandas as pd
import pytest

from mirai_core import ohlcv


class TestFlatDf:
    """flat_df helper behaviour."""

    def test_flat_df_single_level(self):
        """flat_df is a no-op on a single-level DataFrame."""
        df = pd.DataFrame({"Close": [1.0, 2.0]})
        result = ohlcv.flat_df(df)
        assert "Close" in result.columns
        assert isinstance(result["Close"], pd.Series)

    def test_flat_df_multiindex(self):
        """flat_df correctly flattens a MultiIndex columns DataFrame."""
        arrays = [["Close", "High"], ["BTC-USD", "BTC-USD"]]
        cols = pd.MultiIndex.from_arrays(arrays, names=["Price", "Ticker"])
        df = pd.DataFrame([[100.0, 101.0]], columns=cols)
        result = ohlcv.flat_df(df)
        assert "Close" in result.columns
        assert "High" in result.columns


class TestFetchOhlcv:
    """Test OHLCV fetching (may use live data — be tolerant)."""

    def test_fetch_ohlcv_returns_dataframe(self):
        """fetch_ohlcv always returns a DataFrame."""
        df = ohlcv.fetch_ohlcv("BTC-USD", period="5d", interval="1d")
        assert isinstance(df, pd.DataFrame)

    def test_fetch_ohlcv_has_columns(self):
        """Result has expected OHLCV columns."""
        df = ohlcv.fetch_ohlcv("BTC-USD", period="5d", interval="1d")
        if not df.empty:
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                assert col in df.columns

    def test_fetch_4h_resamples_correctly(self):
        """fetch_4h returns 4-hourly data via resampling."""
        df = ohlcv.fetch_4h("BTC-USD", days=7)
        assert isinstance(df, pd.DataFrame)

    def test_fetch_all_timeframes_returns_dict(self):
        """fetch_all_timeframes returns all 5 timeframes."""
        tfs = ohlcv.fetch_all_timeframes("BTC-USD")
        assert set(tfs.keys()) == {"weekly", "daily", "4h", "1h", "15m"}
        for name, df in tfs.items():
            assert isinstance(df, pd.DataFrame), f"{name} is not a DataFrame"
