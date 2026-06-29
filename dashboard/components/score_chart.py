"""
Score Breakdown — horizontal bar chart component.

Renders the 5-dimension analysis score as a colour-coded horizontal
bar chart using Plotly.  Designed for embedding in Streamlit pages
via ``plotly_chart``.

Data shape expected
-------------------
``scores`` dict::

    {
        "regime": 85,        # 0-100 market regime score
        "location": 72,      # 0-100 price location score
        "confirmation": 65,  # 0-100 confirmation / confluence score
        "volume": 78,        # 0-100 volume / liquidity score
        "risk": 55,          # 0-100 risk / reward score
    }
"""

from __future__ import annotations

from typing import Optional

import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIMENSIONS = [
    ("regime", "Market Regime"),
    ("location", "Price Location"),
    ("confirmation", "Confirmation"),
    ("volume", "Volume & Liquidity"),
    ("risk", "Risk / Reward"),
]

# Colour scale:  red  -> amber  -> green
_COLOR_STOPS: list[tuple[float, str]] = [
    (0.3, "#ef4444"),    # 0-30: red (poor)
    (0.65, "#f59e0b"),   # 30-65: amber (neutral)
    (1.0, "#22c55e"),    # 65+: green (good)
]


def _bar_colour(score: float) -> str:
    """Return a hex colour based on the score value (0-100)."""
    ratio = score / 100.0
    for threshold, colour in _COLOR_STOPS:
        if ratio <= threshold:
            return colour
    return _COLOR_STOPS[-1][1]


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


def render_score_chart(
    scores: dict[str, float],
    overall_score: Optional[float] = None,
    key: str = "score_chart",
) -> None:
    """
    Render a horizontal bar chart showing the 5 dimension scores.

    Parameters
    ----------
    scores:
        Dict with keys ``regime``, ``location``, ``confirmation``,
        ``volume``, ``risk`` -- each a float in 0-100.
    overall_score:
        Optional weighted-average score displayed as a title badge.
    key:
        Streamlit widget key (for isolation of multiple instances).
    """
    # Build data in the order we want displayed (bottom-up in the chart)
    labels: list[str] = []
    values: list[float] = []
    colours: list[str] = []
    for key_id, label in reversed(DIMENSIONS):  # reverse so regime is top
        val = scores.get(key_id, 0)
        labels.append(label)
        values.append(val)
        colours.append(_bar_colour(val))

    fig = go.Figure(
        data=go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colours, line=dict(width=0)),
            text=[f"{v:.0f}/100" for v in values],
            textposition="outside",
            textfont=dict(size=13, color="#e2e8f0"),
            hovertemplate="%{y}: %{x:.0f}/100<extra></extra>",
        ),
    )

    # Layout
    title_text = "Score Breakdown"
    if overall_score is not None:
        title_text = f"Score Breakdown \u2014 Overall: {overall_score:.0f}/100"

    fig.update_layout(
        title=dict(
            text=title_text,
            font=dict(size=16, color="#f1f5f9"),
            x=0,
        ),
        xaxis=dict(
            range=[0, 110],
            showgrid=True,
            gridcolor="#334155",
            zeroline=False,
            visible=False,
        ),
        yaxis=dict(
            categoryorder="array",
            categoryarray=labels,
            gridcolor="#334155",
            zeroline=False,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=60, t=40, b=20),
        height=280,
        font=dict(color="#94a3b8"),
    )

    # Remove modebar
    fig.update_xaxes(showticklabels=False)
    fig.update_layout(dragmode=False)
    fig.update_traces(
        cliponaxis=False,
        marker_line=dict(width=0),
    )

    st.plotly_chart(fig, use_container_width=True, key=key)
