"""
Reusable macro dashboard card components.

Designed to be called from ``pages/macro.py``; each function renders a
logical section of the macro dashboard.
"""
from __future__ import annotations

from typing import Any, Optional

import streamlit as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COLOR_BTC = "#F7931A"
_COLOR_USDT = "#26A17B"
_COLOR_DXY = "#1E88E5"
_COLOR_FG = "#FF6B35"
_COLOR_LS = "#9C27B0"
_COLOR_REGIME_RISK_ON = "#00C853"
_COLOR_REGIME_RISK_OFF = "#D32F2F"
_COLOR_REGIME_NEUTRAL = "#FFA000"

_COLORS = {
    "btc_dominance": _COLOR_BTC,
    "usdt_dominance": _COLOR_USDT,
    "dxy": _COLOR_DXY,
    "fear_greed": _COLOR_FG,
    "binance_ls": _COLOR_LS,
}


def _regime_color(regime: str) -> str:
    """Map regime label to a visual colour."""
    r = regime.lower()
    if "on" in r or "bull" in r:
        return _COLOR_REGIME_RISK_ON
    if "off" in r or "bear" in r:
        return _COLOR_REGIME_RISK_OFF
    return _COLOR_REGIME_NEUTRAL


def _card_css() -> str:
    """Inject card styling once per page load."""
    return """
<style>
  .macro-card {
    background: var(--background-color, #1a1a2e);
    border-radius: 12px;
    padding: 1.25rem 1rem;
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    text-align: center;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
  }
  .macro-card:hover {
    border-color: rgba(255,255,255,0.2);
  }
  .macro-card .label {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgba(255,255,255,0.5);
    margin-bottom: 0.5rem;
  }
  .macro-card .value {
    font-size: 1.75rem;
    font-weight: 700;
    line-height: 1.2;
  }
  .macro-card .delta {
    font-size: 0.85rem;
    margin-top: 0.25rem;
  }
  .macro-card .delta.positive { color: #00C853; }
  .macro-card .delta.negative { color: #D32F2F; }
  .macro-card .delta.neutral  { color: #FFA000; }

  /* Regime badge */
  .regime-badge {
    display: inline-block;
    padding: 0.35rem 1.25rem;
    border-radius: 999px;
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: 0.02em;
  }
</style>
"""


def _render_metric_card(
    label: str,
    value: str,
    color: str,
    delta: Optional[str] = None,
    delta_direction: str = "neutral",
) -> None:
    """Render a single macro metric card using HTML."""
    delta_class = delta_direction
    delta_html = (
        f'<div class="delta {delta_class}">{delta}</div>' if delta else ""
    )
    st.markdown(
        f"""
<div class="macro-card">
  <div class="label">{label}</div>
  <div class="value" style="color:{color}">{value}</div>
  {delta_html}
</div>
""",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_macro_cards(data: dict[str, Any]) -> None:
    """
    Render the full macro dashboard card grid.

    Parameters
    ----------
    data : dict
        Expected keys: ``btc_dominance``, ``usdt_dominance``, ``dxy``,
        ``fear_greed_index``, ``fear_greed_label``, ``binance_ls_ratio``,
        ``regime``.  Missing keys are shown as ``"—"``.
    """
    # Inject CSS once
    st.markdown(_card_css(), unsafe_allow_html=True)

    # ---- Row 1: BTC.D, USDT.D, DXY ----
    col1, col2, col3 = st.columns(3)
    with col1:
        btc_d = data.get("btc_dominance")
        _render_metric_card(
            "BTC Dominance",
            f"{btc_d:.1f}%" if btc_d is not None else "—",
            _COLORS["btc_dominance"],
        )
    with col2:
        usdt_d = data.get("usdt_dominance")
        _render_metric_card(
            "USDT Dominance",
            f"{usdt_d:.1f}%" if usdt_d is not None else "—",
            _COLORS["usdt_dominance"],
        )
    with col3:
        dxy = data.get("dxy")
        dxy_error = data.get("dxy_error")
        _render_metric_card(
            "DXY Index",
            f"{dxy:.2f}" if dxy is not None else (dxy_error or "—"),
            _COLORS["dxy"],
        )

    # ---- Row 2: Fear & Greed, L/S Ratio, Regime ----
    col4, col5, col6 = st.columns(3)
    with col4:
        fg_idx = data.get("fear_greed_index")
        fg_label = data.get("fear_greed_label", "")
        fg_display = f"{fg_idx}" if fg_idx is not None else "—"
        if fg_label:
            fg_display += f" · {fg_label}"
        _render_metric_card(
            "Fear & Greed",
            fg_display,
            _COLORS["fear_greed"],
        )
    with col5:
        ls = data.get("binance_ls_ratio")
        _render_metric_card(
            "Binance L/S Ratio",
            f"{ls:.3f}" if ls is not None else "—",
            _COLORS["binance_ls"],
        )
    with col6:
        regime = data.get("regime", "—")
        regime_display = str(regime) if regime else "—"
        rcolor = _regime_color(regime_display)
        st.markdown(
            f"""
<div class="macro-card">
  <div class="label">Regime</div>
  <div style="margin-top: 0.5rem;">
    <span class="regime-badge" style="background:{rcolor}22; color:{rcolor}; border:1px solid {rcolor}55;">
      {regime_display}
    </span>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )


def render_empty_state() -> None:
    """Show a centred placeholder when no macro data is available."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.info(
            "📊 Macro data will appear here once the API is connected.",
            icon="ℹ️",
        )


def render_error_state(error_msg: str) -> None:
    """Show a centred error message."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.error(f"⚠️ Unable to load macro data: {error_msg}", icon="🚨")
