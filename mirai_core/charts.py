"""
Chart rendering — mplfinance candlestick charts + Plotly conversion.

Provides functions to render candlestick charts to mplfinance PNG files
and convert them to Plotly HTML for browser display.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import mplfinance as mpf
import plotly.graph_objects as go


def render_mplfinance(
    df: pd.DataFrame,
    title: str = "Candlestick Chart",
    save_path: str | None = None,
    style: str = "charles",
    bars: int = 50,
    add_indicators: Optional[list[dict]] = None,
) -> str | None:
    """Render a candlestick chart using mplfinance and save to PNG.

    Args:
        df: DataFrame with OHLCV columns.
        title: Chart title.
        save_path: If set, saves PNG to this path.
        style: mplfinance style name.
        bars: Number of bars to show (from the end).
        add_indicators: Optional list of indicator dicts with keys:
            'data' (pd.Series), 'color' (str), 'label' (str).

    Returns:
        save_path if saved, else None.
    """
    if df.empty or len(df) < 10:
        return None

    tail = df.tail(bars)

    ap: list[Any] = []
    if add_indicators:
        for ind in add_indicators:
            data = ind.get("data")
            if data is not None and len(data) >= len(tail):
                ap.append(
                    mpf.make_addplot(
                        data.tail(bars),
                        color=ind.get("color", "blue"),
                        width=ind.get("width", 0.8),
                        label=ind.get("label", ""),
                    )
                )

    kwargs: dict[str, Any] = {
        "type": "candle",
        "style": style,
        "volume": True,
        "title": title,
    }

    if ap:
        kwargs["addplot"] = ap

    if save_path:
        kwargs["savefig"] = dict(
            fname=save_path, dpi=100, bbox_inches="tight"
        )

    mpf.plot(tail, **kwargs)
    return save_path


def convert_to_plotly(df: pd.DataFrame) -> go.Figure:
    """Convert a DataFrame with OHLCV columns to a Plotly candlestick figure.

    Args:
        df: DataFrame with columns Open, High, Low, Close, Volume.

    Returns:
        plotly.graph_objects.Figure.
    """
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Price",
        )
    )

    # Add volume bar chart
    if "Volume" in df.columns:
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df["Volume"],
                name="Volume",
                yaxis="y2",
                marker_color="rgba(100, 100, 255, 0.3)",
            )
        )

    fig.update_layout(
        title="Candlestick Chart",
        xaxis_title="Date",
        yaxis_title="Price (USD)",
        yaxis2=dict(
            title="Volume",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=600,
    )

    return fig


def plotly_to_html(fig: go.Figure) -> str:
    """Convert a Plotly figure to self-contained HTML string."""
    return fig.to_html(include_plotlyjs="cdn", full_html=False)
