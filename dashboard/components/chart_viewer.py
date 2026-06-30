"""
Chart Viewer — interactive Plotly candlestick chart component.

Renders a full-featured candlestick chart with:
- OHLC candles (top panel, 70% height)
- Volume bars (bottom panel, 30% height)
- EMA overlay on price panel
- Order blocks (bullish/bearish) as coloured regions
- Fair Value Gaps (FVGs) as highlighted regions
- Range slider for zoom + date navigation
"""

from __future__ import annotations

from typing import Any, Optional

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OB_COLORS = {
    "bullish": "rgba(34, 197, 94, 0.12)",
    "bearish": "rgba(239, 68, 68, 0.12)",
}

_OB_BORDER = {
    "bullish": "rgba(34, 197, 94, 0.45)",
    "bearish": "rgba(239, 68, 68, 0.45)",
}

_FVG_COLOR = "rgba(250, 204, 21, 0.10)"
_FVG_BORDER = "rgba(250, 204, 21, 0.35)"

_EMA_COLORS: dict[str, str] = {
    "ema_9": "#60a5fa",
    "ema_21": "#f59e0b",
    "ema_50": "#a78bfa",
}

# ---------------------------------------------------------------------------
# Trace builders
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
        "rgba(34, 197, 94, 0.5)" if c["close"] >= c["open"] else "rgba(239, 68, 68, 0.5)"
        for c in candles
    ]
    return go.Bar(
        x=[c["time"] for c in candles],
        y=[c["volume"] for c in candles],
        name="Volume",
        marker=dict(
            color=colours,
            line=dict(width=0),
        ),
        hovertemplate="Vol: %{y:,.0f}<extra></extra>",
        showlegend=False,
    )


def _build_emas(emas: dict[str, list[dict[str, Any]]]) -> list[go.Scatter]:
    traces: list[go.Scatter] = []
    for period in ("ema_9", "ema_21", "ema_50"):
        series = emas.get(period, [])
        if not series:
            continue
        colour = _EMA_COLORS.get(period, "#94a3b8")
        label = period.replace("ema_", "EMA ").upper()
        traces.append(
            go.Scatter(
                x=[s["time"] for s in series],
                y=[s["value"] for s in series],
                mode="lines",
                name=label,
                line=dict(color=colour, width=1.5),
                hovertemplate=f"{label}: %{{y:$,.2f}}<extra></extra>",
                legendgroup="emas",
            )
        )
    return traces


def _build_order_blocks(order_blocks: list[dict[str, Any]]) -> list[go.Scatter]:
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
                hovertext=(
                    f"{label}<br>${ob['price_low']:,.2f} – ${ob['price_high']:,.2f}"
                ),
                hoverinfo="text",
            )
        )
    return traces


def _build_fvgs(fvgs: list[dict[str, Any]]) -> list[go.Scatter]:
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
    """Render an interactive Plotly candlestick chart with volume subplot."""
    if not candles:
        st.info("No candle data available to render.")
        return

    # ── Subplot grid: price (70%) + volume (30%), shared x-axis ────────
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.72, 0.28],
        subplot_titles=("", ""),
    )

    # ── Price panel (row 1) ────────────────────────────────────────────
    fig.add_trace(_build_candlestick(candles), row=1, col=1)

    if emas:
        for trace in _build_emas(emas):
            fig.add_trace(trace, row=1, col=1)

    if order_blocks:
        for trace in _build_order_blocks(order_blocks):
            fig.add_trace(trace, row=1, col=1)

    if fvgs:
        for trace in _build_fvgs(fvgs):
            fig.add_trace(trace, row=1, col=1)

    # ── Volume panel (row 2) ───────────────────────────────────────────
    fig.add_trace(_build_volume(candles), row=2, col=1)

    # ── Layout ─────────────────────────────────────────────────────────
    title = f"{symbol}" if symbol else "Candlestick Chart"

    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=15, color="#e2e8f0"),
            x=0.02,
            xanchor="left",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15, 23, 42, 0.3)",
        font=dict(color="#94a3b8", size=11),
        margin=dict(l=10, r=20, t=40, b=10),
        height=600,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#1e293b",
            font=dict(size=12, color="#e2e8f0"),
            bordercolor="#334155",
        ),
        legend=dict(
            orientation="h",
            y=1.04,
            x=0,
            xanchor="left",
            font=dict(size=10),
            bgcolor="rgba(15, 23, 42, 0.7)",
            bordercolor="#334155",
            borderwidth=1,
        ),
        dragmode="pan",
    )

    # ── Price y-axis (row 1) ───────────────────────────────────────────
    fig.update_yaxes(
        title_text="Price",
        side="right",
        gridcolor="#1e293b",
        zeroline=False,
        tickformat="$,.0f",
        tickfont=dict(color="#94a3b8", size=10),
        row=1, col=1,
    )

    # ── Volume y-axis (row 2) ──────────────────────────────────────────
    fig.update_yaxes(
        title_text="Volume",
        side="right",
        gridcolor="#1e293b",
        zeroline=False,
        tickformat=".2s",
        tickfont=dict(color="#64748b", size=9),
        title_font=dict(color="#64748b", size=10),
        row=2, col=1,
    )

    # ── Shared x-axis ──────────────────────────────────────────────────
    fig.update_xaxes(
        rangeslider=dict(visible=False),
        gridcolor="#1e293b",
        zeroline=False,
        tickfont=dict(color="#94a3b8", size=10),
        row=1, col=1,
    )
    fig.update_xaxes(
        rangeslider=dict(visible=True, thickness=0.06, bgcolor="#1e293b"),
        gridcolor="#1e293b",
        zeroline=False,
        tickfont=dict(color="#64748b", size=9),
        row=2, col=1,
    )

    # ── Modebar ────────────────────────────────────────────────────────
    fig.update_layout(
        modebar=dict(
            bgcolor="rgba(15, 23, 42, 0.5)",
            color="#64748b",
            activecolor="#94a3b8",
            orientation="h",
        ),
    )

    st.plotly_chart(fig, use_container_width=True, key=key)
