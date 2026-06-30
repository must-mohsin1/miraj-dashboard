"""
Chart Viewer — interactive Plotly candlestick chart component.

Renders a full-featured candlestick chart with:
- OHLC candles with volume
- EMA overlay (configurable periods)
- Order blocks (bullish / bearish) as coloured rectangles
- Fair Value Gaps (FVGs) as highlighted regions
- Range slider for zoom + date navigation

Data shapes expected
--------------------
``candles``::

    [
        {"time": "2024-01-01", "open": 42000, "high": 42500,
         "low": 41800, "close": 42300, "volume": 1.2e9},
        ...
    ]

``emas``::

    {
        "ema_9": [{"time": "2024-01-01", "value": 42150}, ...],
        "ema_21": [{"time": "2024-01-01", "value": 41980}, ...],
        "ema_50": [{"time": "2024-01-01", "value": 41500}, ...],
    }

``order_blocks``::

    [
        {
            "start_time": "2024-01-03",
            "end_time": "2024-01-05",
            "price_high": 42500,
            "price_low": 42000,
            "type": "bullish",        # or "bearish"
        },
        ...
    ]

``fvgs``::

    [
        {
            "start_time": "2024-01-07",
            "end_time": "2024-01-08",
            "gap_high": 43000,
            "gap_low": 42700,
        },
        ...
    ]
"""

from __future__ import annotations

from typing import Any, Optional

import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OB_COLORS = {
    "bullish": "rgba(34, 197, 94, 0.15)",
    "bearish": "rgba(239, 68, 68, 0.15)",
}

_OB_BORDER = {
    "bullish": "rgba(34, 197, 94, 0.5)",
    "bearish": "rgba(239, 68, 68, 0.5)",
}

_FVG_COLOR = "rgba(250, 204, 21, 0.12)"
_FVG_BORDER = "rgba(250, 204, 21, 0.4)"

_EMA_COLORS: dict[str, str] = {
    "ema_9": "#60a5fa",    # blue-400
    "ema_21": "#f59e0b",   # amber-500
    "ema_50": "#a78bfa",   # violet-400
}


def _candle_colour(bearish: bool = False) -> str:
    return "#ef4444" if bearish else "#22c55e"


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------


def _build_candlestick(candles: list[dict[str, Any]]) -> go.Candlestick:
    return go.Candlestick(
        x=[c["time"] for c in candles],
        open=[c["open"] for c in candles],
        high=[c["high"] for c in candles],
        low=[c["low"] for c in candles],
        close=[c["close"] for c in candles],
        name="Price",
        increasing=dict(line=dict(color="#22c55e", width=1), fillcolor="#22c55e"),
        decreasing=dict(line=dict(color="#ef4444", width=1), fillcolor="#ef4444"),
        hovertemplate=(
            "<b>%{x}</b><br>"
            "O: %{open:$,.2f}<br>"
            "H: %{high:$,.2f}<br>"
            "L: %{low:$,.2f}<br>"
            "C: %{close:$,.2f}<br>"
            "<extra></extra>"
        ),
        showlegend=False,
    )


def _build_volume(candles: list[dict[str, Any]]) -> go.Bar:
    colours = [
        _candle_colour(bearish=c["close"] < c["open"]) for c in candles
    ]
    return go.Bar(
        x=[c["time"] for c in candles],
        y=[c["volume"] for c in candles],
        name="Volume",
        marker=dict(color=colours, line=dict(width=0)),
        yaxis="y2",
        hovertemplate="Volume: %{y:,.0f}<extra></extra>",
        showlegend=False,
    )


def _build_emas(emas: dict[str, list[dict[str, Any]]]) -> list[go.Scatter]:
    traces: list[go.Scatter] = []
    for period in ("ema_9", "ema_21", "ema_50"):
        series = emas.get(period, [])
        if not series:
            continue
        colour = _EMA_COLORS.get(period, "#94a3b8")
        traces.append(
            go.Scatter(
                x=[s["time"] for s in series],
                y=[s["value"] for s in series],
                mode="lines",
                name=period.upper(),
                line=dict(color=colour, width=1.2),
                hovertemplate=f"{period.upper()}: %{{y:$,.2f}}<extra></extra>",
            )
        )
    return traces


def _build_order_blocks(
    order_blocks: list[dict[str, Any]],
) -> list[go.Scatter]:
    """Render order blocks as filled rectangles via scatter traces."""
    traces: list[go.Scatter] = []
    for i, ob in enumerate(order_blocks):
        ob_type = ob.get("type", "bullish")
        colour = _OB_COLORS.get(ob_type, _OB_COLORS["bullish"])
        border = _OB_BORDER.get(ob_type, _OB_BORDER["bullish"])
        label = f"{'🟢' if ob_type == 'bullish' else '🔴'} OB {ob_type.title()}"

        traces.append(
            go.Scatter(
                x=[ob["start_time"], ob["end_time"], ob["end_time"], ob["start_time"]],
                y=[ob["price_low"], ob["price_low"], ob["price_high"], ob["price_high"]],
                fill="toself",
                fillcolor=colour,
                line=dict(color=border, width=1),
                mode="lines",
                name=label,
                legendgroup=f"ob_{i}",
                showlegend=i == 0,
                hovertext=f"{label}<br>${ob['price_low']:,.2f} \u2013 ${ob['price_high']:,.2f}",
                hoverinfo="text",
            )
        )
    return traces


def _build_fvgs(fvgs: list[dict[str, Any]]) -> list[go.Scatter]:
    """Render FVGs as semi-transparent filled regions."""
    traces: list[go.Scatter] = []
    for i, fvg in enumerate(fvgs):
        traces.append(
            go.Scatter(
                x=[
                    fvg.get("start_time", ""),
                    fvg.get("end_time", ""),
                    fvg.get("end_time", ""),
                    fvg.get("start_time", ""),
                    ],
                    y=[
                    fvg.get("price_low", 0),
                    fvg.get("price_low", 0),
                    fvg.get("price_high", 0),
                    fvg.get("price_high", 0),
                ],
                fill="toself",
                fillcolor=_FVG_COLOR,
                line=dict(color=_FVG_BORDER, width=1, dash="dash"),
                mode="lines",
                name="FVG",
                legendgroup="fvg",
                showlegend=i == 0,
                hovertext=(
                    f"FVG<br>${fvg.get('price_low', 0):,.2f} – ${fvg.get('price_high', 0):,.2f}"
                ),
                hoverinfo="text",
            )
        )
    return traces


# ---------------------------------------------------------------------------
# Public component
# ---------------------------------------------------------------------------


def render_chart(
    candles: list[dict[str, Any]],
    emas: Optional[dict[str, list[dict[str, Any]]]] = None,
    order_blocks: Optional[list[dict[str, Any]]] = None,
    fvgs: Optional[list[dict[str, Any]]] = None,
    symbol: str = "",
    key: str = "chart_viewer",
) -> None:
    """
    Render an interactive Plotly candlestick chart with optional overlays.

    Parameters
    ----------
    candles:
        OHLCV data array (required).
    emas:
        Dict of EMA period to array of {time, value}.
    order_blocks:
        Array of order-block regions (rectangles).
    fvgs:
        Array of FVG regions (highlighted gaps).
    symbol:
        Trading pair label for the chart title.
    key:
        Streamlit widget key for isolation.
    """
    if not candles:
        st.info("No candle data available to render.")
        return

    fig = go.Figure()

    # --- Candles ---
    candlestick = _build_candlestick(candles)
    fig.add_trace(candlestick)

    # --- Volume ---
    volume = _build_volume(candles)
    fig.add_trace(volume)

    # --- EMAs ---
    if emas:
        for trace in _build_emas(emas):
            fig.add_trace(trace)

    # --- Order Blocks ---
    if order_blocks:
        for trace in _build_order_blocks(order_blocks):
            fig.add_trace(trace)

    # --- FVGs ---
    if fvgs:
        for trace in _build_fvgs(fvgs):
            fig.add_trace(trace)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    title = f"Candlestick Chart \u2014 {symbol}" if symbol else "Candlestick Chart"

    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color="#f1f5f9"), x=0),
        # Price axis
        yaxis=dict(
            title="Price (USD)",
            side="right",
            gridcolor="#334155",
            zeroline=False,
            tickformat="$,.0f",
        ),
        # Volume axis
        yaxis2=dict(
            title="Volume",
            overlaying="y",
            side="left",
            position=0,
            showgrid=False,
            zeroline=False,
            visible=False,
        ),
        xaxis=dict(
            rangeslider=dict(visible=True, thickness=0.08),
            type="date",
            gridcolor="#334155",
            zeroline=False,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#94a3b8"),
        margin=dict(l=20, r=80, t=40, b=20),
        height=550,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            y=1.02,
            x=0,
            xanchor="left",
            font=dict(size=11),
            bgcolor="rgba(15, 23, 42, 0.8)",
        ),
        dragmode="zoom",
    )

    st.plotly_chart(fig, use_container_width=True, key=key)
