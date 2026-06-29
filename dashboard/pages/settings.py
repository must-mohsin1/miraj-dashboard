"""
Settings — Watchlist management and user preferences.

Allows the user to:
- View current watchlist pairs with score and status
- Add new pairs (with autocomplete from common pairs)
- Remove pairs (with confirmation dialog)
- Reorder pairs via up/down arrows
- Persist changes via Save button
- Pre-populate with default 15 pairs on first visit
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from dashboard.utils.api_client import (
    add_watchlist_pair,
    get_watchlist,
    remove_watchlist_pair,
    reorder_watchlist,
    set_base_url,
)
from dashboard.utils.session import get_auth_token, get_user_email, is_authenticated, logout

import html

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------
if not is_authenticated():
    st.warning("Please sign in to access this page.")
    st.page_link("app.py", label="Go to Sign In")
    st.stop()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMMON_PAIRS = [
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "DOT-USD", "LINK-USD", "AVAX-USD",
    "MATIC-USD", "ATOM-USD", "LTC-USD", "FIL-USD", "ARB-USD",
    "OP-USD", "INJ-USD", "TIA-USD", "PEPE-USD", "APT-USD",
]

DEFAULT_PAIRS = COMMON_PAIRS[:15]

# Session state keys
_WL_KEY = "watchlist_pairs"
_WL_PREV_KEY = "watchlist_original"  # snapshot for dirty detection
_WL_LOADED_KEY = "watchlist_loaded"
_WL_LOADING_KEY = "watchlist_loading"
_WL_ERROR_KEY = "watchlist_error"
_CONFIRM_KEY = "watchlist_confirm_remove"
_CONFIRM_PAIR_KEY = "watchlist_confirm_pair"


def _init_state() -> None:
    """Ensure all watchlist session keys exist."""
    for key in (_WL_KEY, _WL_PREV_KEY, _WL_LOADED_KEY, _WL_LOADING_KEY, _WL_ERROR_KEY, _CONFIRM_KEY, _CONFIRM_PAIR_KEY):
        if key not in st.session_state:
            if key == _CONFIRM_KEY:
                st.session_state[key] = None  # pair symbol string or None
            elif key == _CONFIRM_PAIR_KEY:
                st.session_state[key] = ""
            elif key in (_WL_LOADED_KEY, _WL_LOADING_KEY):
                st.session_state[key] = False
            else:
                st.session_state[key] = None


_init_state()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_watchlist() -> None:
    """Fetch watchlist from API and store in session state."""
    token = get_auth_token()
    if not token:
        st.session_state[_WL_ERROR_KEY] = "Session expired. Please sign in again."
        return

    st.session_state[_WL_LOADING_KEY] = True
    st.session_state[_WL_ERROR_KEY] = None

    result = get_watchlist(token)
    if result.get("success"):
        data = result.get("data", [])
        # The API returns a bare list of pair dicts
        pairs = data if isinstance(data, list) else data.get("pairs", [])
        st.session_state[_WL_KEY] = pairs
        # Deep copy for dirty comparison
        st.session_state[_WL_PREV_KEY] = [dict(p) for p in pairs]
        st.session_state[_WL_ERROR_KEY] = None
    else:
        st.session_state[_WL_ERROR_KEY] = result.get("error", "Failed to load watchlist")

    st.session_state[_WL_LOADING_KEY] = False


def _is_dirty() -> bool:
    """Check if the current watchlist order differs from the saved original."""
    current = st.session_state.get(_WL_KEY) or []
    original = st.session_state.get(_WL_PREV_KEY) or []
    if len(current) != len(original):
        return True
    for a, b in zip(current, original):
        if a.get("id") != b.get("id") or a.get("sort_order") != b.get("sort_order"):
            return True
    return False


def _move_pair(idx: int, direction: int) -> None:
    """Move pair at *idx* up (-1) or down (+1)."""
    pairs = st.session_state.get(_WL_KEY) or []
    target = idx + direction
    if target < 0 or target >= len(pairs):
        return
    pairs[idx], pairs[target] = pairs[target], pairs[idx]
    # Update sort_order values
    for i, p in enumerate(pairs):
        p["sort_order"] = i
    st.session_state[_WL_KEY] = pairs


def _add_pair(pair: str) -> None:
    """Add a pair to the watchlist via API, then refresh."""
    token = get_auth_token()
    if not token:
        st.error("Session expired. Please sign in again.")
        return

    with st.spinner(f"Adding {pair}…"):
        result = add_watchlist_pair(pair, token)

    if result.get("success"):
        st.success(f"Added {pair}")
        _fetch_watchlist()
    else:
        st.error(result.get("error", f"Failed to add {pair}"))


def _remove_pair(pair_id: int, pair_symbol: str) -> None:
    """Remove a pair from the watchlist via API by database id."""
    token = get_auth_token()
    if not token:
        st.error("Session expired. Please sign in again.")
        return

    with st.spinner(f"Removing {pair_symbol}…"):
        result = remove_watchlist_pair(pair_id, token)

    if result.get("success"):
        st.success(f"Removed {pair_symbol}")
        st.session_state[_CONFIRM_KEY] = None
        st.session_state[_CONFIRM_PAIR_KEY] = ""
        _fetch_watchlist()
    else:
        st.error(result.get("error", f"Failed to remove {pair_symbol}"))


def _save_order() -> None:
    """Persist the current order via PUT /api/v1/watchlist/reorder."""
    token = get_auth_token()
    if not token:
        st.error("Session expired. Please sign in again.")
        return

    pairs = st.session_state.get(_WL_KEY) or []
    pair_ids = [p["id"] for p in pairs]

    with st.spinner("Saving order…"):
        result = reorder_watchlist(pair_ids, token)

    if result.get("success"):
        st.success("Watchlist order saved!")
        # Update original snapshot
        st.session_state[_WL_PREV_KEY] = [dict(p) for p in pairs]
    else:
        st.error(result.get("error", "Failed to save order"))


def _seed_default_pairs() -> None:
    """Add all default pairs to the watchlist."""
    token = get_auth_token()
    if not token:
        st.error("Session expired.")
        return

    added = 0
    errors: list[str] = []
    existing_pairs = {p["pair"] for p in (st.session_state.get(_WL_KEY) or [])}

    for pair in DEFAULT_PAIRS:
        if pair in existing_pairs:
            continue
        result = add_watchlist_pair(pair, token)
        if result.get("success"):
            added += 1
        else:
            error = result.get("error", "Unknown error")
            errors.append(f"{pair}: {error}")

    if added:
        st.success(f"Added {added} default pair(s).")
    if errors:
        for err in errors:
            st.warning(err)

    _fetch_watchlist()


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def _is_valid_pair(pair: str) -> bool:
    """Basic validation for pair format like BTC-USD or BTCUSDT."""
    if not pair or len(pair) < 5:
        return False
    # Accept dash-separated (BTC-USD) or concatenated (BTCUSDT)
    if "-" in pair:
        parts = pair.split("-")
        return len(parts) == 2 and all(p.strip() for p in parts)
    return True


# ---------------------------------------------------------------------------
# Inject custom CSS for the watchlist table
# ---------------------------------------------------------------------------

st.markdown(
    """
<style>
  .wl-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }
  .wl-row:last-child {
    border-bottom: none;
  }
  .wl-pair-name {
    font-weight: 600;
    font-size: 0.95rem;
    min-width: 8rem;
  }
  .wl-score {
    font-size: 0.85rem;
    min-width: 4rem;
    text-align: center;
  }
  .wl-status {
    font-size: 0.8rem;
    min-width: 5rem;
    text-align: center;
  }
  .wl-status.active {
    color: #00C853;
  }
  .wl-score .empty {
    color: rgba(255,255,255,0.35);
  }
  .wl-actions {
    display: flex;
    gap: 0.25rem;
  }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------------

st.title("⚙️ Settings")

user_email = get_user_email() or "—"
st.markdown(f"**Account:** {user_email}")

st.markdown("---")

# =========================================================================
# Watchlist Section
# =========================================================================

st.subheader("👁️ Watchlist")
st.caption(
    "Manage the trading pairs you want to monitor. "
    "Add, remove, and reorder pairs; then click **Save Order** to persist changes."
)

# ---- Fetch watchlist on first load ----
if not st.session_state.get(_WL_LOADED_KEY):
    _fetch_watchlist()
    st.session_state[_WL_LOADED_KEY] = True

# ---- Loading state ----
if st.session_state.get(_WL_LOADING_KEY):
    st.info("Loading watchlist…")
    st.progress(0.5, text="Fetching your pairs")

# ---- Error state ----
error = st.session_state.get(_WL_ERROR_KEY)
if error and not st.session_state.get(_WL_LOADING_KEY):
    st.error(f"⚠️ {error}")
    if st.button("🔄 Retry", type="secondary"):
        _fetch_watchlist()
        st.rerun()

# ---- Watchlist content ----
pairs: list[dict[str, Any]] = st.session_state.get(_WL_KEY) or []

if not pairs and not st.session_state.get(_WL_LOADING_KEY) and not error:
    # ---- Empty state ----
    st.info(
        "Your watchlist is empty. Add pairs below, or click **Seed Default Pairs** "
        "to populate with common trading pairs.",
        icon="ℹ️",
    )
    if st.button("🌱 Seed Default Pairs", type="primary"):
        _seed_default_pairs()
        st.rerun()

# ---- Render pairs ----
if pairs:
    # Column headers
    col_idx, col_pair, col_score, col_status, col_actions, col_remove = st.columns(
        [0.5, 2, 1.2, 1.2, 2.5, 0.8]
    )
    with col_idx:
        st.caption("#")
    with col_pair:
        st.caption("**Pair**")
    with col_score:
        st.caption("**Score**")
    with col_status:
        st.caption("**Status**")
    with col_actions:
        st.caption("**Reorder**")
    with col_remove:
        st.caption("")

    # Pair rows
    for idx, pair in enumerate(pairs):
        pair_id = pair.get("id")
        pair_name = pair.get("pair", "—")
        score = pair.get("score")
        status = pair.get("status", "Active")
        is_first = idx == 0
        is_last = idx == len(pairs) - 1

        cols = st.columns([0.5, 2, 1.2, 1.2, 2.5, 0.8])

        with cols[0]:
            st.markdown(f"<span style='color:rgba(255,255,255,0.4); font-size:0.85rem;'>{idx + 1}</span>", unsafe_allow_html=True)

        with cols[1]:
            st.markdown(f"<span class='wl-pair-name'>{html.escape(pair_name)}</span>", unsafe_allow_html=True)

        with cols[2]:
            if score is not None:
                score_color = "#00C853" if score >= 60 else "#FFA000" if score >= 30 else "#D32F2F"
                st.markdown(f"<span style='color:{score_color}; font-weight:600;'>{score:.0f}</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:rgba(255,255,255,0.25);'>—</span>", unsafe_allow_html=True)

        with cols[3]:
            st.markdown(f"<span class='wl-status active'>● {html.escape(status)}</span>", unsafe_allow_html=True)

        with cols[4]:
            btn_up = st.button(
                "▲",
                key=f"up_{pair_id}",
                disabled=is_first,
                help="Move up",
                use_container_width=True,
            )
            btn_down = st.button(
                "▼",
                key=f"down_{pair_id}",
                disabled=is_last,
                help="Move down",
                use_container_width=True,
            )

            if btn_up:
                _move_pair(idx, -1)
                st.rerun()
            if btn_down:
                _move_pair(idx, 1)
                st.rerun()

        with cols[5]:
            if st.button("✕", key=f"rm_{pair_id}", help=f"Remove {pair_name}", use_container_width=True):
                st.session_state[_CONFIRM_KEY] = pair_id
                st.session_state[_CONFIRM_PAIR_KEY] = pair_name
                st.rerun()

    # ---- Save / Discard buttons ----
    dirty = _is_dirty()
    col_save, col_discard, _ = st.columns([1, 1, 4])
    with col_save:
        st.button(
            "💾 Save Order",
            type="primary",
            disabled=not dirty,
            use_container_width=True,
            on_click=_save_order,
        )
    with col_discard:
        if dirty:
            if st.button("↩ Discard Changes", use_container_width=True):
                # Restore original order
                original = st.session_state.get(_WL_PREV_KEY) or []
                st.session_state[_WL_KEY] = [dict(p) for p in original]
                st.rerun()

# =========================================================================
# Confirmation dialog (remove pair)
# =========================================================================

confirm_pair = st.session_state.get(_CONFIRM_KEY)
confirm_pair_name = st.session_state.get(_CONFIRM_PAIR_KEY, "")

if confirm_pair is not None:
    with st.container(border=True):
        st.markdown(f"**Remove {confirm_pair_name}?**")
        st.caption("This will remove the pair from your watchlist. This action cannot be undone.")

        col_yes, col_no = st.columns([1, 1])
        with col_yes:
            if st.button("Yes, remove", type="primary", key="confirm_remove_yes", use_container_width=True):
                _remove_pair(confirm_pair, confirm_pair_name)
                st.rerun()
        with col_no:
            if st.button("Cancel", key="confirm_remove_no", use_container_width=True):
                st.session_state[_CONFIRM_KEY] = None
                st.session_state[_CONFIRM_PAIR_KEY] = ""
                st.rerun()

# =========================================================================
# Add pair form
# =========================================================================

st.markdown("---")
st.markdown("### ➕ Add Pair")

with st.form("add_pair_form", clear_on_submit=True):
    # Autocomplete: selectbox with common pairs + custom entry via text_input
    add_mode = st.radio(
        "Choose method",
        ["Select from common pairs", "Type custom pair"],
        horizontal=True,
        key="add_mode_radio",
        label_visibility="collapsed",
    )

    pair_to_add: Optional[str] = None

    if add_mode == "Select from common pairs":
        pair_to_add = st.selectbox(
            "Trading pair",
            options=[""] + COMMON_PAIRS,
            format_func=lambda x: "Select a pair…" if x == "" else x,
            key="add_pair_select",
        )
    else:
        pair_to_add = st.text_input(
            "Trading pair",
            placeholder="e.g. SOL-USD, AVAX-USD",
            key="add_pair_text",
            max_chars=20,
        )

    submitted = st.form_submit_button("➕ Add to Watchlist", type="primary", use_container_width=True)

    if submitted:
        pair_val = (pair_to_add or "").strip().upper()
        if not pair_val:
            st.warning("Please select or enter a trading pair.")
        elif not _is_valid_pair(pair_val):
            st.warning(
                "Invalid pair format. Use format like **BTC-USD** or **ETH-USD**."
            )
        else:
            _add_pair(pair_val)
            st.rerun()

st.markdown("---")

# =========================================================================
# API Configuration & Logout
# =========================================================================

with st.expander("API Configuration", expanded=False):
    current_url = st.session_state.get("api_base_url", "http://localhost:8000")
    new_url = st.text_input("Backend API URL", value=current_url)
    if st.button("Save", type="primary"):
        set_base_url(new_url)
        st.session_state.api_base_url = new_url
        st.success("API URL updated.")

st.markdown("---")

if st.button("🚪 Logout", type="secondary"):
    logout()
    st.rerun()
