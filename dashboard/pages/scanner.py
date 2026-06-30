"""Scanner — multi-pair scan results in a sortable table.

Displays watchlist pairs with their confluence scores, trade direction,
and analysis time. Supports sorting, individual re-scan, and batch scan.

Data flow
---------
1. Page load → fetch watchlist → show pairs
2. "Scan All" → POST /api/v1/scan/batch → populate table
3. Per-pair "Rescan" → POST /api/v1/scan/{symbol} → update row
4. Row selection → navigate to analysis detail with ?symbol=XXX
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import pandas as pd
import streamlit as st

from dashboard.utils.api_client import (
    get_watchlist,
    scan_batch,
    scan_symbol,
)
from dashboard.utils.session import get_auth_token, is_authenticated

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------
if not is_authenticated():
    st.warning("Please sign in to access this page.")
    st.page_link("app.py", label="Go to Sign In")
    st.stop()

# ---------------------------------------------------------------------------
# Constants & session state
# ---------------------------------------------------------------------------
_BATCH_KEY = "scanner_batch_data"    # raw dict from batch scan endpoint
_PAIRS_KEY = "scanner_pairs"         # list of symbol strings
_LOADING_KEY = "scanner_loading"
_ERROR_KEY = "scanner_error"
_RESCAN_KEY = "scanner_rescan_symbol"  # single-pair rescan in progress


def _init_state() -> None:
    for key in (_BATCH_KEY, _PAIRS_KEY, _LOADING_KEY, _ERROR_KEY, _RESCAN_KEY):
        if key not in st.session_state:
            st.session_state[key] = None


_init_state()


def _format_time(ts: Any) -> str:
    """Format a timestamp for display."""
    if ts is None:
        return "—"
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, TypeError):
            return ts[:19]
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return str(ts)


def _direction_icon(direction: Optional[str]) -> str:
    if not direction:
        return "⚪"
    d = direction.upper()
    return "🟢" if d == "LONG" else "🔴" if d == "SHORT" else "⚪"


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _load_watchlist(token: str) -> list[str]:
    """Return the user's watchlist as a list of symbol strings."""
    result = get_watchlist(token)
    if not result.get("success"):
        return []
    data = result.get("data", {})
    # The data may be a list of pairs or an object with a "pairs" key
    if isinstance(data, list):
        pairs_raw = data
    elif isinstance(data, dict):
        pairs_raw = data.get("pairs", data.get("results", []))
    else:
        pairs_raw = []
    symbols: list[str] = []
    for p in pairs_raw:
        if isinstance(p, dict):
            sym = p.get("pair", p.get("symbol", p.get("name", "")))
        elif isinstance(p, str):
            sym = p
        else:
            continue
        if sym:
            symbols.append(sym.upper().strip())
    return symbols


def _extract_rows(batch_data: dict) -> list[dict[str, Any]]:
    """Convert batch scan response into flat row dicts for the DataFrame."""
    results = batch_data.get("results", [])
    if not results:
        return []

    rows: list[dict[str, Any]] = []
    for item in results:
        symbol = item.get("symbol", "—")
        success = item.get("success", "error" not in item)

        if not success:
            rows.append({
                "symbol": symbol,
                "score": None,
                "direction": "ERROR",
                "direction_icon": "❌",
                "analysis_time": "—",
                "error": item.get("error", "Unknown error"),
            })
            continue

        tp = item.get("trade_plan") or {}
        direction = (tp.get("direction") or item.get("direction") or "—").upper()

        rows.append({
            "symbol": symbol,
            "score": item.get("overall_score") or item.get("confluence_score"),
            "direction": direction,
            "direction_icon": _direction_icon(direction),
            "analysis_time": _format_time(
                item.get("analysis_time")
                or tp.get("analysis_time")
            ),
            "error": None,
        })

    return rows


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------
token = get_auth_token()
if not token:
    st.error("Session expired. Please sign in again.")
    st.stop()

assert token is not None  # narrow type for Pyright

# ---------------------------------------------------------------------------
# Load watchlist on first access
# ---------------------------------------------------------------------------
if st.session_state[_PAIRS_KEY] is None:
    st.session_state[_PAIRS_KEY] = _load_watchlist(token)

pairs: list[str] = st.session_state[_PAIRS_KEY]

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.title("🔍 Scanner")
st.markdown(
    "Run confluence analysis across your entire watchlist, "
    "or drill into individual trading pairs."
)

# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------
if not pairs:
    col_icon, col_msg = st.columns([1, 8])
    with col_icon:
        st.markdown("### 📭")
    with col_msg:
        st.markdown(
            "**Your watchlist is empty.**\n\n"
            "Add trading pairs in **Settings → Watchlist** to get started."
        )
        if st.button("⚙️ Go to Watchlist Settings", type="secondary"):
            st.switch_page("pages/settings.py")
    st.stop()

# ---------------------------------------------------------------------------
# Error banner
# ---------------------------------------------------------------------------
error_msg = st.session_state.get(_ERROR_KEY)
if error_msg:
    st.error(f"⚠️ {error_msg}")

# ---------------------------------------------------------------------------
# Scan All + status bar
# ---------------------------------------------------------------------------
batch_data = st.session_state.get(_BATCH_KEY)
is_loading = bool(st.session_state.get(_LOADING_KEY))
rescan_symbol = st.session_state.get(_RESCAN_KEY)

col_btn, col_info = st.columns([1, 3])

with col_btn:
    scan_all_clicked = st.button(
        "🔄 Scan All",
        type="primary",
        use_container_width=True,
        disabled=is_loading,
        help="Run analysis on every pair in your watchlist.",
    )

with col_info:
    if batch_data:
        total = batch_data.get("total", 0)
        succeeded = batch_data.get("succeeded", 0)
        failed = batch_data.get("failed", 0)
        if failed:
            st.markdown(
                f"**{succeeded}** of **{total}** analysed — "
                f"<span style='color:#ef4444'>{failed} failed</span>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f" **{total}** pairs analysed")

# ---------------------------------------------------------------------------
# Handle Scan All
# ---------------------------------------------------------------------------
if scan_all_clicked:
    st.session_state[_LOADING_KEY] = True
    st.session_state[_ERROR_KEY] = None
    with st.spinner("Running batch analysis on all watchlist pairs…"):
        result = scan_batch(token)
    if result.get("success"):
        st.session_state[_BATCH_KEY] = result.get("data", {})
        st.session_state[_ERROR_KEY] = None
    else:
        st.session_state[_ERROR_KEY] = result.get("error", "Batch scan failed.")
        st.session_state[_BATCH_KEY] = None
    st.session_state[_LOADING_KEY] = False
    st.rerun()

# ---------------------------------------------------------------------------
# Handle per-pair rescan (triggered by the "Rescan" button below the table)
# ---------------------------------------------------------------------------
if rescan_symbol and isinstance(rescan_symbol, str):
    st.session_state[_LOADING_KEY] = True
    st.session_state[_ERROR_KEY] = None
    with st.spinner(f"Re-analysing **{rescan_symbol}**…"):
        result = scan_symbol(rescan_symbol, token)
    if result.get("success"):
        # Merge the single result into the existing batch data
        scan_result = result.get("data", {})
        existing_raw = st.session_state.get(_BATCH_KEY) or {}
        existing_results = existing_raw.get("results", []) if isinstance(existing_raw, dict) else []

        # Replace or append the result for this symbol
        found = False
        for i, r in enumerate(existing_results):
            if isinstance(r, dict) and r.get("symbol", "").upper().strip() == rescan_symbol:
                existing_results[i] = {
                    "symbol": scan_result.get("symbol", rescan_symbol),
                    "success": True,
                    "overall_score": scan_result.get("overall_score") or scan_result.get("confluence_score"),
                    "confluence_score": scan_result.get("confluence_score", 0.0),
                    "trade_plan": scan_result.get("trade_plan", {}),
                    "score_breakdown": scan_result.get("score_breakdown"),
                    "analysis_time": scan_result.get("analysis_time")
                                   or scan_result.get("trade_plan", {}).get("analysis_time"),
                    "error": None,
                }
                found = True
                break

        if not found:
            existing_results.append({
                "symbol": scan_result.get("symbol", rescan_symbol),
                "success": True,
                "overall_score": scan_result.get("overall_score") or scan_result.get("confluence_score"),
                "confluence_score": scan_result.get("confluence_score", 0.0),
                "trade_plan": scan_result.get("trade_plan", {}),
                "score_breakdown": scan_result.get("score_breakdown"),
                "analysis_time": scan_result.get("analysis_time")
                               or scan_result.get("trade_plan", {}).get("analysis_time"),
                "error": None,
            })

        new_count = min(
            existing_raw.get("total", len(existing_results)) if isinstance(existing_raw, dict) else len(existing_results),
            len(existing_results)
        )
        st.session_state[_BATCH_KEY] = {
            "results": existing_results,
            "total": len(existing_results),
            "succeeded": sum(1 for r in existing_results if r.get("success", False)),
            "failed": sum(1 for r in existing_results if not r.get("success", False)),
        }
        st.session_state[_ERROR_KEY] = None
    else:
        st.session_state[_ERROR_KEY] = result.get(
            "error", f"Analysis failed for {rescan_symbol}."
        )
    st.session_state[_RESCAN_KEY] = None
    st.session_state[_LOADING_KEY] = False
    st.rerun()

# ---------------------------------------------------------------------------
# Loading indicator (still loading, no results yet)
# ---------------------------------------------------------------------------
if is_loading and batch_data is None:
    st.info("Analysis in progress… results will appear automatically.")
    st.progress(0.5, text="Scanning watchlist pairs…")
    st.stop()

# ---------------------------------------------------------------------------
# Build table data
# ---------------------------------------------------------------------------
rows: list[dict[str, Any]] = []

if batch_data:
    rows = _extract_rows(batch_data)

# If we have pairs but no batch results yet, show "not scanned" placeholder
if not rows and pairs:
    rows = [
        {
            "symbol": s,
            "score": None,
            "direction": "—",
            "direction_icon": "⚪",
            "analysis_time": "—",
            "error": "Not scanned yet",
        }
        for s in pairs
    ]

# ---------------------------------------------------------------------------
# Render the sortable table
# ---------------------------------------------------------------------------
if rows:
    df = pd.DataFrame(rows)

    # Configure column display
    column_config = {
        "direction_icon": st.column_config.TextColumn(
            "", width="small", help="Trade direction"
        ),
        "symbol": st.column_config.TextColumn(
            "Symbol", width="medium",
            help="Click a row to view the full analysis",
        ),
        "score": st.column_config.NumberColumn(
            "Score",
            width="small",
            format="%.0f",
            help="Confluence score (0–100)",
        ),
        "direction": st.column_config.TextColumn(
            "Direction", width="small",
        ),
        "analysis_time": st.column_config.TextColumn(
            "Analysis Time", width="medium",
        ),
    }

    # Reset selection tracking for navigation dedup
    if "_scan_nav_target" not in st.session_state:
        st.session_state["_scan_nav_target"] = None

    event = st.dataframe(
        df,
        column_config=column_config,
        use_container_width=True,
        hide_index=True,
        column_order=["direction_icon", "symbol", "score", "direction", "analysis_time"],
        on_select="rerun",
        selection_mode="single-row",
        key="scanner_results_table",
    )

    # --- Detect row selection → navigate to detail page ---
    selected_rows: list[int] = []
    if event and hasattr(event, "selection") and event.selection:
        try:
            selected_rows = list(event.selection.rows or [])
        except (AttributeError, TypeError):
            selected_rows = []

    if selected_rows:
        idx = selected_rows[0]
        row = df.iloc[idx]
        selected_symbol = str(row["symbol"])

        # De-duplicate navigation: only navigate once per symbol click
        last_nav = st.session_state["_scan_nav_target"]
        if last_nav != selected_symbol:
            st.session_state["_scan_nav_target"] = selected_symbol
            st.query_params["symbol"] = selected_symbol
            st.switch_page("pages/analysis.py")

        # Show action buttons while row is selected
        st.markdown(f"**{selected_symbol}** selected")
        row_action_cols = st.columns([1, 1, 4])

        with row_action_cols[0]:
            if st.button("📊 View Analysis", type="primary", use_container_width=True):
                st.query_params["symbol"] = selected_symbol
                st.switch_page("pages/analysis.py")

        with row_action_cols[1]:
            if st.button("🔄 Rescan", type="secondary", use_container_width=True):
                st.session_state[_RESCAN_KEY] = selected_symbol
                st.rerun()
    else:
        st.caption(
            "💡 Click a row above to view the full analysis or re-scan a pair."
        )
        # Clear nav target when no row is selected
        st.session_state["_scan_nav_target"] = None

    # --- Per-pair scan button fallback (if dataframe selection is not supported) ---
    # Also render inline page links for quick access
    st.markdown("")
    st.markdown("**Quick links:**")
    link_cols = st.columns(min(len(pairs), 6))
    for i, sym in enumerate(pairs):
        col_idx = i % len(link_cols)
        with link_cols[col_idx]:
            st.page_link(
                f"pages/analysis.py?symbol={sym}",
                label=f"{sym}",
            )

# ---------------------------------------------------------------------------
# No data fallback
# ---------------------------------------------------------------------------
else:
    st.info(
        "ℹ️ No scan results yet. Click **Scan All** above to analyse "
        "all pairs in your watchlist.",
        icon="🔍",
    )
