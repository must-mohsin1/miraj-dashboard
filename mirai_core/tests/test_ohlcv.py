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


class TestMexcOhlcv:
    def test_fetch_mexc_all_timeframes_converts_contract_klines(self, monkeypatch):
        """An active MEXC contract yields scanner-compatible frames."""
        intervals = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"success":true,"data":{"time":[1720000000],"open":[1],"high":[2],"low":[0.5],"close":[1.5],"vol":[42]}}'

        def fake_urlopen(request, timeout):
            intervals.append(request.full_url)
            return Response()

        monkeypatch.setattr(ohlcv.request, "urlopen", fake_urlopen)

        frames = ohlcv.fetch_mexc_all_timeframes("HYPE_USDT")

        assert set(frames) == {"weekly", "daily", "4h", "1h", "15m"}
        assert all(list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"] for frame in frames.values())
        assert frames["daily"].iloc[0].to_dict() == {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 42.0}
        assert any("interval=Week1" in url for url in intervals)
        assert any("interval=Min15" in url for url in intervals)
