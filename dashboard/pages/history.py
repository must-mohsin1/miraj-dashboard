"""
History — browse, filter, export, and delete past analyses.

Data flow
---------
1. Page mount → GET /api/v1/history?page=1&per_page=20
2. Filter change → re-fetch with query params
3. "View" → set query param ?symbol=PAIR → st.switch_page to analysis.py
4. "Delete" → confirm → DELETE /api/v1/history/{id} → re-fetch
5. "Export" → GET /api/v1/history/export?ids=... → download markdown
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import streamlit as st

from dashboard.utils.api_client import (
    delete_analysis,
    export_history,
    get_history,
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
# Session state keys
# ---------------------------------------------------------------------------
_HISTORY_KEY = "history_data"
_LOADING_KEY = "history_loading"
_ERROR_KEY = "history_error"
_DELETE_KEY = "history_delete_pending_id"
_SELECTED_KEY = "history_selected_ids"
_SYMBOLS_KEY = "history_available_symbols"

_PAGE_KEY = "history_page"
_PER_PAGE_KEY = "history_per_page"
_FILTER_SYMBOL_KEY = "history_filter_symbol"
_FILTER_FROM_KEY = "history_filter_from"
_FILTER_TO_KEY = "history_filter_to"
_FILTER_SCORE_KEY = "history_filter_min_score"
_EXPORT_DL_KEY = "history_export_dl"

_DEFAULT_PER_PAGE = 20


def _init_state() -> None:
    """Ensure all session-state keys exist."""
    defaults: dict[str, Any] = {
        _HISTORY_KEY: None,
        _LOADING_KEY: False,
        _ERROR_KEY: None,
        _DELETE_KEY: None,
        _SELECTED_KEY: [],
        _SYMBOLS_KEY: [],
        _PAGE_KEY: 1,
        _PER_PAGE_KEY: _DEFAULT_PER_PAGE,
        _FILTER_SYMBOL_KEY: "All",
        _FILTER_FROM_KEY: None,
        _FILTER_TO_KEY: None,
        _FILTER_SCORE_KEY: 0,
        _EXPORT_DL_KEY: None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


_init_state()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch(page: int | None = None) -> None:
    """Fetch history data from the backend and store in session state."""
    token = get_auth_token()
    if not token:
        st.session_state[_ERROR_KEY] = "Session expired. Please sign in again."
        st.session_state[_LOADING_KEY] = False
        return

    p = page if page is not None else st.session_state.get(_PAGE_KEY, 1)
    pp = st.session_state.get(_PER_PAGE_KEY, _DEFAULT_PER_PAGE)

    # Build filter params — only send non-default values
    symbol_param: Optional[str] = None
    sym = st.session_state.get(_FILTER_SYMBOL_KEY, "All")
    if sym != "All" and sym != "None":
        symbol_param = sym

    from_param: Optional[str] = None
    frm = st.session_state.get(_FILTER_FROM_KEY)
    if frm and isinstance(frm, date):
        from_param = frm.isoformat()

    to_param: Optional[str] = None
    to_ = st.session_state.get(_FILTER_TO_KEY)
    if to_ and isinstance(to_, date):
        to_param = to_.isoformat()

    score_param: Optional[float] = None
    score = st.session_state.get(_FILTER_SCORE_KEY, 0)
    if score and score > 0:
        score_param = float(score)

    st.session_state[_LOADING_KEY] = True
    st.session_state[_ERROR_KEY] = None

    result = get_history(
        token=token,
        page=p,
        per_page=pp,
        symbol=symbol_param,
        from_date=from_param,
        to_date=to_param,
        min_score=score_param,
    )

    if result.get("success"):
        st.session_state[_HISTORY_KEY] = result["data"]
        st.session_state[_PAGE_KEY] = p

        # Cache available symbols from the first page for the dropdown
        rows = result["data"].get("rows", [])
        symbols = sorted({r["symbol"] for r in rows})
        if symbols:
            st.session_state[_SYMBOLS_KEY] = symbols
    else:
        st.session_state[_ERROR_KEY] = result.get("error", "Failed to load history.")
        st.session_state[_HISTORY_KEY] = None

    st.session_state[_LOADING_KEY] = False


def _format_dt(raw: str | None) -> str:
    """Format an ISO timestamp for table display."""
    if not raw:
        return "—"
    try:
        dt_val = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt_val.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return raw


def _score_color(score: float | None) -> str:
    """Colour hex for the score badge."""
    if score is None:
        return "#6b7280"
    if score >= 70:
        return "#22c55e"
    if score >= 50:
        return "#eab308"
    return "#ef4444"


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------

st.title("📜 History")
st.markdown("Browse your past scans and saved analyses.")

# ── Filters section ─────────────────────────────────────────────────────────

st.subheader("🔎 Filters", divider="grey")

col_sym, col_from, col_to, col_score, col_btn = st.columns([1.5, 1, 1, 1, 0.8])

with col_sym:
    available = ["All"] + st.session_state[_SYMBOLS_KEY]
    current_sym = st.session_state[_FILTER_SYMBOL_KEY]
    sym_idx = available.index(current_sym) if current_sym in available else 0
    st.selectbox(
        "Symbol",
        options=available,
        index=sym_idx,
        key=_FILTER_SYMBOL_KEY,
    )

with col_from:
    st.date_input(
        "From",
        key=_FILTER_FROM_KEY,
        format="YYYY-MM-DD",
    )

with col_to:
    st.date_input(
        "To",
        key=_FILTER_TO_KEY,
        format="YYYY-MM-DD",
    )

with col_score:
    st.slider(
        "Min Score",
        min_value=0,
        max_value=100,
        key=_FILTER_SCORE_KEY,
        step=5,
    )

with col_btn:
    st.markdown("&nbsp;")
    st.markdown("&nbsp;")
    if st.button("🔍 Apply Filters", use_container_width=True, type="primary"):
        st.session_state[_PAGE_KEY] = 1
        st.session_state[_EXPORT_DL_KEY] = None
        st.session_state[_HISTORY_KEY] = None  # clear cache to trigger re-fetch
        st.rerun()

# ── Actions bar ─────────────────────────────────────────────────────────────

col_a1, col_a2 = st.columns([1, 1])

with col_a1:
    selected_ids = st.session_state.get(_SELECTED_KEY, [])
    if st.button(
        "📥 Export Selected",
        use_container_width=True,
        disabled=len(selected_ids) == 0,
        type="secondary",
    ):
        token = get_auth_token()
        if token and selected_ids:
            with st.spinner("Generating report…"):
                export_result = export_history(selected_ids, token)
            if export_result.get("success"):
                st.session_state[_EXPORT_DL_KEY] = export_result["data"]
            else:
                st.error(export_result.get("error", "Export failed."))

    # Show download button if we have export content
    export_md = st.session_state.get(_EXPORT_DL_KEY)
    if export_md:
        st.download_button(
            label="⬇️ Download Markdown Report",
            data=export_md,
            file_name=f"analysis_report_{date.today().isoformat()}.md",
            mime="text/markdown",
            use_container_width=True,
        )

with col_a2:
    if st.button("🔄 Clear Filters", use_container_width=True, type="secondary"):
        st.session_state[_FILTER_SYMBOL_KEY] = "All"
        st.session_state[_FILTER_FROM_KEY] = None
        st.session_state[_FILTER_TO_KEY] = None
        st.session_state[_FILTER_SCORE_KEY] = 0
        st.session_state[_PAGE_KEY] = 1
        st.session_state[_SELECTED_KEY] = []
        st.session_state[_EXPORT_DL_KEY] = None
        st.session_state[_HISTORY_KEY] = None  # clear cache to trigger re-fetch
        st.rerun()

st.markdown("---")

# ── Auto-fetch on first load ────────────────────────────────────────────────

data = st.session_state.get(_HISTORY_KEY)
if data is None and not st.session_state.get(_LOADING_KEY):
    _fetch()
    st.rerun()

# ── Loading state ───────────────────────────────────────────────────────────

if st.session_state.get(_LOADING_KEY):
    st.info("⏳ Loading analysis history…")
    st.progress(0.5, text="Fetching data from server")
    st.stop()

# ── Error state ─────────────────────────────────────────────────────────────

error = st.session_state.get(_ERROR_KEY)
if error:
    st.error(f"⚠️ {error}")
    if st.button("🔄 Retry", type="secondary"):
        st.session_state[_ERROR_KEY] = None
        _fetch()
        st.rerun()
    st.stop()

# ── Empty state ─────────────────────────────────────────────────────────────

if not data or not data.get("rows"):
    st.info(
        "ℹ️ No analyses found. "
        "Run a scan on the **Scanner** or **Analysis** pages first.",
        icon="ℹ️",
    )
    st.stop()

# ── Data table ──────────────────────────────────────────────────────────────

rows: list[dict[str, Any]] = data["rows"]
total: int = data["total"]
page_cur: int = data["page"]
pages_total: int = data["pages"]

st.caption(
    f"Showing **{len(rows)}** of **{total}** analyses — "
    f"Page **{page_cur}** of **{pages_total}**"
)

# ── Table header ────────────────────────────────────────────────────────────

HEADER_STYLE = (
    "font-weight:600;font-size:0.85rem;color:#9ca3af;"
    "text-transform:uppercase;letter-spacing:0.05em;"
)

hdr = st.columns([0.45, 1.6, 1.2, 0.9, 1.1, 0.8, 1.6])
labels = ["Sel.", "Date", "Symbol", "Score", "Direction", "Alert", "Actions"]
for col, label in zip(hdr, labels):
    col.markdown(
        f"<span style='{HEADER_STYLE}'>{label}</span>",
        unsafe_allow_html=True,
    )

st.markdown(
    "<div style='border-bottom:1px solid #374151;margin-bottom:0.5rem;'></div>",
    unsafe_allow_html=True,
)

# ── Table rows ──────────────────────────────────────────────────────────────

selected_ids = list(st.session_state.get(_SELECTED_KEY, []))
pending_delete = st.session_state.get(_DELETE_KEY)
current_ids = {r["id"] for r in rows}

for i, row in enumerate(rows):
    row_id = row["id"]
    is_pending = pending_delete == row_id
    bg = "#1f2937" if is_pending else "#111827" if i % 2 == 0 else "#0f172a"

    # Row background wrapper
    st.markdown(
        f"<div style='background:{bg};padding:0.3rem 0;border-radius:4px;'>",
        unsafe_allow_html=True,
    )

    cols = st.columns([0.45, 1.6, 1.2, 0.9, 1.1, 0.8, 1.6])

    # Sel. checkbox
    with cols[0]:
        is_checked = row_id in selected_ids
        checked = st.checkbox(
            "##",
            value=is_checked,
            key=f"sel_{row_id}",
            label_visibility="collapsed",
        )
        if checked and row_id not in selected_ids:
            selected_ids.append(row_id)
        elif not checked and row_id in selected_ids:
            selected_ids.remove(row_id)

    # Date
    with cols[1]:
        st.markdown(_format_dt(row.get("created_at")))

    # Symbol
    with cols[2]:
        st.markdown(f"**{row['symbol']}**")

    # Score
    with cols[3]:
        score = row.get("score")
        if score is not None:
            color = _score_color(score)
            st.markdown(
                f"<span style='color:{color};font-weight:600;'>{score:.0f}</span>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<span style='color:#6b7280;'>—</span>",
                unsafe_allow_html=True,
            )

    # Direction
    with cols[4]:
        direction = row.get("direction")
        if direction == "LONG":
            st.markdown("🟢 **LONG**")
        elif direction == "SHORT":
            st.markdown("🔴 **SHORT**")
        else:
            st.markdown("⚪ —")

    # Alert Sent
    with cols[5]:
        st.markdown("✅ Sent" if row.get("alert_sent") else "—")

    # Actions
    with cols[6]:
        act = st.columns([1, 1])
        with act[0]:
            if st.button("👁 View", key=f"view_{row_id}", use_container_width=True):
                # Set query param BEFORE navigating
                st.query_params["symbol"] = row["symbol"]
                st.switch_page("pages/analysis.py")

        with act[1]:
            if is_pending:
                # Confirm / Cancel inline
                confirm_c = st.columns([1, 1])
                with confirm_c[0]:
                    if st.button("✓", key=f"cfm_{row_id}", use_container_width=True):
                        token = get_auth_token()
                        if token:
                            del_result = delete_analysis(row_id, token)
                            if del_result.get("success"):
                                st.session_state[_DELETE_KEY] = None
                                st.session_state[_SELECTED_KEY] = [
                                    i for i in selected_ids if i != row_id
                                ]
                                _fetch()
                                st.rerun()
                            else:
                                st.error(del_result.get("error", "Delete failed."))
                        st.session_state[_DELETE_KEY] = None
                        st.rerun()
                with confirm_c[1]:
                    if st.button("✗", key=f"cnl_{row_id}", use_container_width=True):
                        st.session_state[_DELETE_KEY] = None
                        st.rerun()
            else:
                if st.button("🗑", key=f"del_{row_id}", use_container_width=True):
                    st.session_state[_DELETE_KEY] = row_id
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# Persist selection state
st.session_state[_SELECTED_KEY] = [i for i in selected_ids if i in current_ids]

# ── Pagination controls ─────────────────────────────────────────────────────

st.markdown("---")

if pages_total > 1:
    page_controls = st.columns([1, 3, 1, 1])

    # Prev
    with page_controls[0]:
        prev_disabled = page_cur <= 1
        if st.button("◀ Prev", disabled=prev_disabled, use_container_width=True, type="secondary"):
            _fetch(page_cur - 1)
            st.rerun()

    # Page numbers
    with page_controls[1]:
        # Show up to 10 page buttons around the current page
        lo = max(1, page_cur - 4)
        hi = min(pages_total, page_cur + 5)
        page_range = list(range(lo, hi + 1))
        sub_cols = st.columns(len(page_range))
        for idx, p in enumerate(page_range):
            with sub_cols[idx]:
                is_current = p == page_cur
                if st.button(
                    str(p),
                    key=f"pg_{p}",
                    type="primary" if is_current else "secondary",
                    use_container_width=True,
                ):
                    _fetch(p)
                    st.rerun()

    # Next
    with page_controls[2]:
        next_disabled = page_cur >= pages_total
        if st.button("Next ▶", disabled=next_disabled, use_container_width=True, type="secondary"):
            _fetch(page_cur + 1)
            st.rerun()

    # Per-page selector
    with page_controls[3]:
        pp_options = [10, 20, 50, 100]
        current_pp = st.session_state.get(_PER_PAGE_KEY, _DEFAULT_PER_PAGE)
        try:
            pp_idx = pp_options.index(current_pp)
        except ValueError:
            pp_idx = 1
        new_pp = st.selectbox(
            "Per page",
            options=pp_options,
            index=pp_idx,
            key="pp_sel",
            label_visibility="collapsed",
        )
        if new_pp != current_pp:
            st.session_state[_PER_PAGE_KEY] = new_pp
            st.session_state[_PAGE_KEY] = 1
            st.session_state[_HISTORY_KEY] = None  # clear cache
            st.rerun()
else:
    st.caption(f"Page 1 of 1 — {total} total analyses")
