"""
Tests for macro module — data fetching from live APIs.

All tests attempt live API calls and gracefully handle temporary failures.
"""
from mirai_core.macro import (
    fetch_coingecko_global,
    fetch_usdt_dominance,
    fetch_fear_greed,
    fetch_long_short_ratio,
    fetch_dxy,
    fetch_macro_data,
)


class TestMacro:
    """Test macro data fetching from live APIs."""

    def test_fetch_coingecko_global_has_keys(self):
        """fetch_coingecko_global returns BTC.D, ETH.D, total_mcap, altcoin_mcap."""
        data = fetch_coingecko_global()
        for key in ("btc_d", "eth_d", "total_mcap", "altcoin_mcap"):
            assert key in data, f"Missing key: {key}"
        assert data["btc_d"] is not None and data["btc_d"] > 0
        assert data["eth_d"] is not None and data["eth_d"] > 0

    def test_fetch_usdt_dominance_returns_float(self):
        """USDT.D returns a valid percentage."""
        usdt_d = fetch_usdt_dominance()
        assert isinstance(usdt_d, float)
        assert 0 < usdt_d < 100

    def test_fetch_fear_greed_has_value(self):
        """Fear & Greed returns value and classification."""
        fng = fetch_fear_greed()
        assert "value" in fng
        assert "value_classification" in fng
        val = int(fng["value"])
        assert 0 <= val <= 100

    def test_fetch_long_short_ratio_btc(self):
        """Binance L/S ratio returns data for BTC."""
        ls = fetch_long_short_ratio("BTCUSDT")
        assert ls is not None
        assert "longShortRatio" in ls
        assert float(ls["longShortRatio"]) > 0

    def test_fetch_dxy_returns_float_or_none(self):
        """DXY fetch returns float or None (graceful failure)."""
        dxy = fetch_dxy()
        assert dxy is None or isinstance(dxy, float)

    def test_fetch_macro_data_has_all_keys(self):
        """fetch_macro_data returns all required macro keys."""
        data = fetch_macro_data()
        for key in (
            "btc_d",
            "eth_d",
            "usdt_d",
            "total_mcap",
            "fear_greed",
            "dxy",
            "long_short_ratio_btc",
        ):
            assert key in data, f"Missing key: {key}"
        # btc_d should be a positive number
        if data["btc_d"] is not None:
            assert data["btc_d"] > 0
        # fear_greed should have value
        if data["fear_greed"] is not None:
            assert "value" in data["fear_greed"]
