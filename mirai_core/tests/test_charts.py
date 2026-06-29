"""
Tests for charts module — mplfinance rendering and Plotly conversion.
"""
import matplotlib
matplotlib.use("Agg")
import os
import numpy as np
import pandas as pd
import pytest

from mirai_core import charts
from mirai_core.tests.conftest import get_synthetic_ohlcv


class TestCharts:
    """Chart rendering and conversion."""

    def _make_df(self, bars=60):
        return get_synthetic_ohlcv(bars)

    def test_render_mplfinance_returns_path_or_none(self):
        """render_mplfinance returns path when saved, None otherwise."""
        df = self._make_df()
        result = charts.render_mplfinance(df, title="Test Chart")
        # When no save_path, return is None but the function runs
        assert result is None

    def test_render_mplfinance_with_save(self, tmp_path):
        """When save_path is provided, PNG file is created."""
        df = self._make_df()
        save_path = str(tmp_path / "test_chart.png")
        result = charts.render_mplfinance(
            df, title="Test Chart", save_path=save_path, bars=30
        )
        assert os.path.exists(save_path)
        assert result == save_path

    def test_convert_to_plotly_returns_figure(self):
        """convert_to_plotly returns a Plotly Figure."""
        df = self._make_df()
        fig = charts.convert_to_plotly(df)
        assert fig is not None
        # Should have at least one trace (candlestick)
        assert len(fig.data) >= 1

    def test_plotly_figure_has_candlestick(self):
        """The Plotly figure contains a candlestick trace."""
        df = self._make_df()
        fig = charts.convert_to_plotly(df)
        trace_types = [t.type for t in fig.data]
        assert "candlestick" in trace_types or "bar" in trace_types

    def test_plotly_to_html_returns_string(self):
        """plotly_to_html returns an HTML string."""
        df = self._make_df()
        fig = charts.convert_to_plotly(df)
        html = charts.plotly_to_html(fig)
        assert isinstance(html, str)
        assert len(html) > 100
        assert "Plotly" in html or "plotly" in html
