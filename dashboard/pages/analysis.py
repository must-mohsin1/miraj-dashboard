"""
Analysis Detail — full analysis result page.

Displays scan results with:
- Interactive Plotly candlestick chart (EMA, OB, FVG annotations)
- Score breakdown horizontal bar chart
- Trade plan with entry / stop / target levels

Query parameters
----------------
``?symbol=BTC-USD`` — auto-loads the latest analysis for that pair.

Data flow
---------
1. Page mount: if ``symbol`` in query params -> ``GET /api/v1/scan/{symbol}``
2. "Run Analysis" button -> ``POST /api/v1/scan/{symbol}`` -> spinner -> result
3. Result cached in ``st.session_state.analysis_result`` per symbol
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from dashboard.components.chart_viewer import render_chart
from dashboard.components.score_chart import render_score_chart
from dashboard.utils.api_client import get_analysis, scan_symbol
from dashboard.utils.session import get_auth_token, is_authenticated

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------
if not is_authenticated():
    st.warning("Please sign in to access this page.")
    st.page_link("app.py", label="Go to Sign In")
    st.stop()

# ---------------------------------------------------------------------------
# Session state keys
# ---------------------------------------------------------------------------
_RESULT_KEY = "analysis_result"
_SYMBOL_KEY = "analysis_symbol"
_LOADING_KEY = "analysis_loading"
_ERROR_KEY = "analysis_error"


def _init_state() -> None:
    """Ensure session-state keys exist."""
    for key in (_RESULT_KEY, _SYMBOL_KEY, _LOADING_KEY, _ERROR_KEY):
        if key not in st.session_state:
            st.session_state[key] = None


_init_state()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_query_symbol() -> Optional[str]:
    """Return the ``symbol`` query param, or None."""
    params = st.query_params
    raw = params.get("symbol")
    if raw and isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _format_price(value: Optional[float], decimals: int = 2) -> str:
    """Format a price for display."""
    if value is None:
        return "—"
    if value >= 1000:
        return f"${value:,.{decimals}f}"
    return f"${value:.{decimals}f}"


def _format_risk_reward(
    entry: float, target: float, stop: float, direction: str
) -> str:
    """Calculate and format risk:reward ratio."""
    if entry == stop:
        return "—"
    if direction.upper() == "LONG":
        r_multiple = (target - entry) / (entry - stop)
    else:
        r_multiple = (entry - target) / (stop - entry)
    return f"1:{r_multiple:.1f}"


def _run_analysis(symbol: str) -> None:
    """Trigger a new analysis via POST and store result in session state."""
    token = get_auth_token()
    if not token:
        st.session_state[_ERROR_KEY] = "Session expired. Please sign in again."
        st.session_state[_LOADING_KEY] = False
        return

    st.session_state[_LOADING_KEY] = True
    st.session_state[_ERROR_KEY] = None
    st.session_state[_RESULT_KEY] = None
    st.session_state[_SYMBOL_KEY] = symbol

    with st.spinner(f"Running analysis for **{symbol}**\u2026"):
        result = scan_symbol(symbol, token)

    if result.get("success"):
        st.session_state[_RESULT_KEY] = result.get("data")
        st.session_state[_ERROR_KEY] = None
    else:
        st.session_state[_ERROR_KEY] = result.get(
            "error", "Analysis failed. Please try again."
        )
        st.session_state[_RESULT_KEY] = None

    st.session_state[_LOADING_KEY] = False
    st.rerun()


def _load_existing(symbol: str) -> None:
    """Try to load an existing analysis result via GET."""
    token = get_auth_token()
    if not token:
        return

    st.session_state[_SYMBOL_KEY] = symbol
    st.session_state[_LOADING_KEY] = True

    with st.spinner(f"Loading analysis for **{symbol}**\u2026"):
        result = get_analysis(symbol, token)

    if result.get("success"):
        st.session_state[_RESULT_KEY] = result.get("data")
        st.session_state[_ERROR_KEY] = None
    else:
        st.session_state[_RESULT_KEY] = None
        st.session_state[_ERROR_KEY] = None

    st.session_state[_LOADING_KEY] = False


# ---------------------------------------------------------------------------
# Trade plan sub-component (defined before use)
# ---------------------------------------------------------------------------


def _render_trade_plan(
    direction: str,
    entry: float,
    stop: Optional[float],
    targets: list[float],
    raw: dict[str, Any],
) -> None:
    """Render the trade plan section with entry/stop/targets."""
    is_long = direction.upper() == "LONG"

    badge = "🟢 **LONG**" if is_long else "🔴 **SHORT**"
    st.markdown(f"**Direction:** {badge}")

    st.markdown(f"**Entry:** {_format_price(entry)}")

    if stop is not None:
        stop_dist = abs(entry - stop) / entry * 100
        st.markdown(
            f"**Stop Loss:** {_format_price(stop)} "
            f"<span style='color:#ef4444'>({stop_dist:.2f}%)</span>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("**Stop Loss:** —")

    if targets:
        st.markdown("**Targets:**")
        for i, tgt in enumerate(targets, 1):
            rr = (
                _format_risk_reward(entry, tgt, stop, direction)
                if stop is not None and stop != entry
                else "—"
            )
            progress_pct = abs(tgt - entry) / abs(stop - entry) * 100 if stop and stop != entry else 0
            st.markdown(
                f"&nbsp;&nbsp;**T{i}:** {_format_price(tgt)} &nbsp;"
                f"<span style='color:#22c55e'>(R:R {rr})</span>",
                unsafe_allow_html=True,
            )
            st.progress(min(progress_pct / 100, 1.0), text=f"Target {i}")
    else:
        st.markdown("**Targets:** —")

    rationale = raw.get("rationale") or raw.get("notes")
    if rationale:
        st.markdown("---")
        st.markdown(f"**Rationale:** {rationale}")

    notes = raw.get("notes")
    if notes and notes != rationale:
        st.caption(notes)


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------

st.title("📋 Analysis Detail")
st.markdown(
    "Run a new analysis on any trading pair or view the latest saved results."
)

# --- Symbol input + Run button ---

col_sym, col_btn = st.columns([3, 1])

with col_sym:
    symbol_input = st.text_input(
        "Trading Pair",
        value=st.session_state.get(_SYMBOL_KEY) or "BTC-USD",
        placeholder="e.g. BTC-USD, ETH-USD",
        key="symbol_input",
        help="Enter a crypto trading pair symbol.",
    )

with col_btn:
    st.markdown("&nbsp;")
    st.markdown("&nbsp;")
    run_clicked = st.button(
        "▶ Run Analysis",
        type="primary",
        use_container_width=True,
        disabled=bool(st.session_state.get(_LOADING_KEY)),
    )

if run_clicked and symbol_input and symbol_input.strip():
    _run_analysis(symbol_input.strip())

# --- Auto-load from query param (only on first load) ---

query_sym = _get_query_symbol()
if query_sym and not st.session_state.get(_RESULT_KEY):
    if query_sym != st.session_state.get(_SYMBOL_KEY):
        _load_existing(query_sym)

# --- Error state ---

error = st.session_state.get(_ERROR_KEY)
if error:
    st.error(f"⚠️ {error}")
    if st.button("🔄 Retry", type="secondary"):
        sym = st.session_state.get(_SYMBOL_KEY, symbol_input)
        if sym:
            _run_analysis(sym)

# --- Loading indicator ---

if st.session_state.get(_LOADING_KEY):
    st.info("Analysis in progress\u2026 results will appear automatically.")
    st.progress(0.5, text="Analyzing market structure\u2026")

# --- Results ---

result: Optional[dict[str, Any]] = st.session_state.get(_RESULT_KEY)
if result is None and not error and not st.session_state.get(_LOADING_KEY):
    st.info(
        "ℹ️ No analysis loaded yet. Enter a symbol and click **Run Analysis**, "
        "or add **?symbol=BTC-USD** to the URL.",
        icon="ℹ️",
    )

if result is not None:
    data = result if isinstance(result, dict) else {}
    sym = data.get("symbol", st.session_state.get(_SYMBOL_KEY, "—"))

    st.markdown("---")

    # --- Summary row ---
    overall = data.get("overall_score")
    # Use trade_plan_flat for flat keys, fall back to trade_plan
    tp_flat = data.get("trade_plan_flat") or {}
    trade_plan_raw = data.get("trade_plan", {})
    direction = tp_flat.get("direction") or trade_plan_raw.get("direction", "—")
    entry = tp_flat.get("entry")
    dir_icon = "🟢" if direction.upper() == "LONG" else "🔴" if direction.upper() == "SHORT" else "⚪"

    cols_summary = st.columns(4)
    with cols_summary[0]:
        st.metric("Symbol", sym)
    with cols_summary[1]:
        st.metric(
            "Overall Score",
            f"{overall:.0f}/100" if overall is not None else "—",
        )
    with cols_summary[2]:
        st.metric("Direction", f"{dir_icon} {direction.title()}")
    with cols_summary[3]:
        st.metric("Entry Price", _format_price(entry))

    # --- Two-column layout: Score + Trade Plan ---
    col_left, col_right = st.columns([1, 1])

    with col_left:
        scores = data.get("scores", {})
        if isinstance(scores, dict) and scores:
            render_score_chart(scores, overall_score=overall, key="analysis_scores")
        else:
            st.caption("Score data not available.")

    with col_right:
        st.subheader("📝 Trade Plan")
        flat_tp = data.get("trade_plan_flat") or {}
        raw_tp = data.get("trade_plan", {})
        if flat_tp.get("entry") is not None:
            entry_val = flat_tp["entry"]
            stop = flat_tp.get("stop_loss")
            targets: list[float] = []
            for k in ("target_1", "target_2", "target_3"):
                v = flat_tp.get(k)
                if v is not None:
                    targets.append(v)
            _render_trade_plan(flat_tp.get("direction", "LONG"), entry_val, stop, targets, raw_tp)
        else:
            st.caption("No trade plan available for this analysis.")

    # --- Chart ---
    st.markdown("---")
    st.subheader("📊 Price Chart")

    candles = data.get("candles", [])
    emas = data.get("emas", {})
    order_blocks = data.get("order_blocks", [])
    fvgs = data.get("fvgs", [])

    if candles:
        render_chart(
            candles=candles,
            emas=emas if isinstance(emas, dict) else {},
            order_blocks=order_blocks if isinstance(order_blocks, list) else [],
            fvgs=fvgs if isinstance(fvgs, list) else [],
            symbol=sym,
            key="analysis_chart",
        )
    else:
        st.caption("Candle data not available for chart rendering.")
