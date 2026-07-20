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


ZONE_META_KEYS = (
    "timeframe", "age_bars", "age_days", "distance_pct",
    "direction_match", "actionable", "reason",
)


class TestZoneMetadata:
    """Detection-time actionability metadata on order blocks and FVGs."""

    def _make_ob_df(self, final_price=102.0, bars=30):
        """30 bars of 4H data with exactly one bullish OB: zone (99, 101) at bar 10.

        Bars 0-9 are flat at 100, bar 10 is the base candle (99-101),
        bar 11 the impulse (+2.5 body vs base range 2.0), bar 12 the
        continuation close above the impulse, bars 13+ flat at
        ``final_price``. Flat candles have zero body so they can never
        qualify as impulses and create no further order blocks.
        """
        idx = pd.date_range("2024-01-01", periods=bars, freq="4h")
        rows = []
        for i in range(bars):
            if i < 10:
                rows.append((100.0, 100.5, 99.5, 100.0))
            elif i == 10:
                rows.append((100.0, 101.0, 99.0, 100.0))
            elif i == 11:
                rows.append((100.0, 102.6, 99.9, 102.5))
            elif i == 12:
                rows.append((102.5, 103.2, 102.3, 103.0))
            else:
                p = final_price
                rows.append((p, p + 0.4, p - 0.4, p))
        df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
        df["Volume"] = 1000
        return df

    def _make_fvg_df(self, bars=10):
        """10 bars of 4H data with exactly one bullish FVG: zone (100.5, 102) at bar 5."""
        idx = pd.date_range("2024-01-01", periods=bars, freq="4h")
        rows = []
        for i in range(bars):
            if i < 5:
                rows.append((100.0, 100.5, 99.5, 100.0))
            elif i == 5:
                rows.append((100.0, 103.5, 99.8, 103.0))
            elif i == 6:
                rows.append((103.0, 104.0, 102.0, 103.5))
            else:
                rows.append((102.5, 103.0, 102.2, 102.5))
        df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
        df["Volume"] = 1000
        return df

    def test_nearby_bullish_ob_is_actionable_with_full_metadata(self):
        """A zone ~1% below spot carries age/distance metadata and is actionable."""
        df = self._make_ob_df(final_price=102.0)
        obs = smc.find_order_blocks(df)
        assert len(obs) == 1
        ob = obs[0]
        # backward-compatible detection keys unchanged
        assert ob["type"] == "Bullish"
        assert ob["zone"] == (99.0, 101.0)
        assert ob["index"] == df.index[10]
        # additive actionability metadata
        assert ob["timeframe"] == "4h"
        assert ob["age_bars"] == 19
        assert ob["age_days"] == pytest.approx(19 * 4 / 24, abs=0.01)
        assert ob["distance_pct"] == pytest.approx(-0.9804, abs=1e-3)
        assert ob["direction_match"] == "bullish"
        assert ob["actionable"] is True
        assert "within" in ob["reason"]

    def test_far_zone_is_not_actionable(self):
        """A zone >3% below spot is visible but not actionable."""
        df = self._make_ob_df(final_price=110.0)
        obs = smc.find_order_blocks(df)
        assert len(obs) == 1
        ob = obs[0]
        assert ob["distance_pct"] == pytest.approx((101 - 110) / 110 * 100, abs=1e-3)
        assert ob["actionable"] is False
        assert "beyond" in ob["reason"]

    def test_wrong_side_zone_is_not_actionable(self):
        """Price below a bullish zone is not a pullback — zone not actionable."""
        df = self._make_ob_df(final_price=95.0)
        obs = smc.find_order_blocks(df)
        assert len(obs) == 1
        ob = obs[0]
        assert ob["distance_pct"] == pytest.approx((99 - 95) / 95 * 100, abs=1e-3)
        assert ob["actionable"] is False
        assert "not positioned" in ob["reason"]

    def test_fvg_carries_actionability_metadata(self):
        """FVGs are annotated with the same metadata schema as order blocks."""
        df = self._make_fvg_df()
        fvgs = smc.find_fvgs(df)
        assert len(fvgs) == 1
        fvg = fvgs[0]
        assert fvg["type"] == "Bullish"
        assert fvg["zone"] == (100.5, 102.0)
        assert fvg["timeframe"] == "4h"
        assert fvg["age_bars"] == 4
        assert fvg["age_days"] == pytest.approx(4 * 4 / 24, abs=0.01)
        assert fvg["distance_pct"] == pytest.approx(-0.4878, abs=1e-3)
        assert fvg["direction_match"] == "bullish"
        assert fvg["actionable"] is True

    def test_analyze_threads_timeframe_to_zone_metadata(self):
        """analyze(timeframe=...) stamps every OB and FVG with that timeframe."""
        df = self._make_ob_df()
        result = smc.analyze(df, timeframe="1h")
        assert result["order_blocks"] and result["fvgs"]
        assert all(ob["timeframe"] == "1h" for ob in result["order_blocks"])
        assert all(f["timeframe"] == "1h" for f in result["fvgs"])

    def test_metadata_schema_is_stable(self):
        """Every detected zone carries every metadata key, even on random data."""
        df = TestSMC()._make_synthetic_4h()
        for zone in smc.find_order_blocks(df) + smc.find_fvgs(df):
            for key in ZONE_META_KEYS:
                assert key in zone

    def test_annotate_zones_handles_missing_index_and_price(self):
        """Hand-built zones without index and empty frames degrade to None fields."""
        df = self._make_ob_df()
        zones = smc.annotate_zones(
            [{"type": "Bearish", "zone": (110.0, 112.0)}], df, timeframe="daily"
        )
        z = zones[0]
        assert z["timeframe"] == "daily"
        assert z["age_bars"] is None and z["age_days"] is None
        assert z["direction_match"] == "bearish"
        assert z["distance_pct"] == pytest.approx((110 - 102) / 102 * 100, abs=1e-3)
        assert z["actionable"] is False  # 7.8% above spot — beyond pullback range

        empty = smc.annotate_zones([{"type": "Bullish", "zone": (1.0, 2.0)}], pd.DataFrame())
        assert empty[0]["distance_pct"] is None
        assert empty[0]["actionable"] is False
        assert "price unavailable" in empty[0]["reason"]
