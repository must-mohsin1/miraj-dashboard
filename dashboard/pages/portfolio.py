"""
Portfolio — MEXC exchange portfolio view.

Displays spot balances, futures positions, and recent trades.
Data flow:
1. Page load → GET /api/v1/portfolio/mexc/keys → check connection
2. If disconnected → show connect form
3. If connected → 3 tabs (Balances, Positions, Trades) with cached data
4. Refresh button → POST /api/v1/portfolio/mexc/refresh → update tabs
5. Disconnect button → DELETE /api/v1/portfolio/mexc/disconnect
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import requests
import streamlit as st

from dashboard.utils.session import get_auth_token, is_authenticated

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

import os

_EXCHANGE = "mexc"
_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

if not is_authenticated():
    st.warning("Please sign in to access this page.")
    st.page_link("app.py", label="Go to Sign In")
    st.stop()

token = get_auth_token()
if not token:
    st.error("Session expired. Please sign in again.")
    st.stop()

_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "portfolio_data" not in st.session_state:
    st.session_state.portfolio_data = None
if "portfolio_connected" not in st.session_state:
    st.session_state.portfolio_connected = None
if "portfolio_error" not in st.session_state:
    st.session_state.portfolio_error = None
if "portfolio_last_refresh" not in st.session_state:
    st.session_state.portfolio_last_refresh = None


def _api_get(path: str) -> dict:
    """GET request to backend API."""
    try:
        r = requests.get(f"{_BASE_URL}{path}", headers=_headers, timeout=15)
        return r.json() if r.status_code == 200 else {"error": r.json().get("detail", "Unknown error")}
    except Exception as e:
        return {"error": str(e)}


def _api_post(path: str, json_body: dict = None) -> dict:
    """POST request to backend API."""
    try:
        r = requests.post(f"{_BASE_URL}{path}", headers=_headers, json=json_body or {}, timeout=30)
        return r.json() if r.status_code in (200, 201) else {"error": r.json().get("detail", "Unknown error")}
    except Exception as e:
        return {"error": str(e)}


def _api_delete(path: str) -> bool:
    """DELETE request to backend API."""
    try:
        r = requests.delete(f"{_BASE_URL}{path}", headers=_headers, timeout=10)
        return r.status_code in (200, 204)
    except Exception:
        return False


def _check_connection() -> dict | None:
    """Check if MEXC is connected. Returns keys info or None."""
    result = _api_get(f"/api/v1/portfolio/{_EXCHANGE}/keys")
    if "error" in result:
        return None
    return result


def _load_cached() -> dict | None:
    """Load cached portfolio data from backend."""
    result = _api_get(f"/api/v1/portfolio/{_EXCHANGE}")
    if "error" in result:
        return None
    return result


def _format_usd(val: Any) -> str:
    """Format a value as USD."""
    if val is None:
        return "—"
    try:
        v = float(val)
        if v >= 1000:
            return f"${v:,.2f}"
        return f"${v:.4f}"
    except (ValueError, TypeError):
        return "—"


def _format_pct(val: Any) -> str:
    """Format a value as percentage."""
    if val is None:
        return "—"
    try:
        return f"{float(val):+.2f}%"
    except (ValueError, TypeError):
        return "—"


def _time_ago(dt_str: str | None) -> str:
    """Human readable 'X min ago' from ISO datetime string."""
    if not dt_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = (now - dt).total_seconds()
        if diff < 60:
            return "Just now"
        if diff < 3600:
            return f"{int(diff / 60)} min ago"
        return f"{int(diff / 3600)}h ago"
    except Exception:
        return "—"


# ---------------------------------------------------------------------------
# Page title
# ---------------------------------------------------------------------------

st.title("💼 Portfolio")
st.markdown("View your MEXC exchange balances, positions, and recent trades.")

# ---------------------------------------------------------------------------
# Check connection state
# ---------------------------------------------------------------------------

if st.session_state.portfolio_connected is None:
    keys_info = _check_connection()
    st.session_state.portfolio_connected = (
        keys_info.get("connected", False) if keys_info else False
    )

# Load cached data on first visit if connected
if st.session_state.portfolio_connected and st.session_state.portfolio_data is None:
    cached = _load_cached()
    if cached and "error" not in cached:
        st.session_state.portfolio_data = cached
        st.session_state.portfolio_last_refresh = cached.get("last_refreshed")

# ---------------------------------------------------------------------------
# Disconnected state — show connect form
# ---------------------------------------------------------------------------

if not st.session_state.portfolio_connected:
    st.markdown("### 🔑 Connect MEXC Exchange")
    st.markdown(
        "Enter your MEXC API key and secret to view your portfolio. "
        "Keys are encrypted at rest and never stored in plain text."
    )

    with st.form("connect_mexc"):
        api_key = st.text_input("API Key", placeholder="Enter your MEXC API key", type="password")
        api_secret = st.text_input("API Secret", placeholder="Enter your MEXC API secret", type="password")
        submitted = st.form_submit_button("🔗 Connect", type="primary", use_container_width=True)

    if submitted:
        if not api_key or not api_secret:
            st.error("Please enter both API key and secret.")
        else:
            with st.spinner("Validating credentials…"):
                result = _api_post(
                    f"/api/v1/portfolio/{_EXCHANGE}/connect",
                    {"api_key": api_key, "api_secret": api_secret},
                )
            if "error" in result:
                st.error(f"Connection failed: {result['error']}")
            else:
                st.success("Connected to MEXC! Loading portfolio…")
                st.session_state.portfolio_connected = True
                st.session_state.portfolio_data = result
                st.session_state.portfolio_last_refresh = datetime.now(timezone.utc).isoformat()
                st.rerun()

    st.markdown("---")
    st.caption("Get your API key from MEXC → API Management. Enable 'Read' permission only.")
    st.stop()

# ---------------------------------------------------------------------------
# Connected state — show portfolio data
# ---------------------------------------------------------------------------

# --- Top bar: refresh + disconnect ---

col1, col2, col3 = st.columns([1, 1, 2])

with col1:
    if st.button("🔄 Refresh", type="primary", use_container_width=True):
        with st.spinner("Fetching from MEXC…"):
            result = _api_post(f"/api/v1/portfolio/{_EXCHANGE}/refresh")
        if "error" in result:
            st.session_state.portfolio_error = result["error"]
        else:
            st.session_state.portfolio_data = result
            st.session_state.portfolio_last_refresh = result.get("last_refreshed")
            st.session_state.portfolio_error = None
            st.rerun()

with col2:
    if st.button("🔌 Disconnect", use_container_width=True, type="secondary"):
        # Confirmation dialog
        st.session_state["show_disconnect_confirm"] = True

with col3:
    refresh_time = _time_ago(st.session_state.portfolio_last_refresh)
    st.markdown(f"**Last refreshed:** {refresh_time}")

# --- Disconnect confirmation ---
if st.session_state.get("show_disconnect_confirm"):
    with st.dialog("Disconnect MEXC?"):
        st.markdown("This will remove your API keys and clear all cached portfolio data.")
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("Confirm", type="primary", use_container_width=True):
                if _api_delete(f"/api/v1/portfolio/{_EXCHANGE}/disconnect"):
                    st.session_state.portfolio_connected = False
                    st.session_state.portfolio_data = None
                    st.session_state.portfolio_last_refresh = None
                    st.session_state["show_disconnect_confirm"] = False
                    st.rerun()
                else:
                    st.error("Failed to disconnect. Try again.")
        with dc2:
            if st.button("Cancel", use_container_width=True):
                st.session_state["show_disconnect_confirm"] = False
                st.rerun()

# --- Error banner ---
error = st.session_state.get("portfolio_error")
if error:
    st.error(f"⚠️ {error}")
    if st.button("🔄 Retry"):
        st.session_state.portfolio_error = None
        st.rerun()

# --- Portfolio data ---
data = st.session_state.portfolio_data

if not data:
    st.info("No portfolio data yet. Click Refresh to fetch from MEXC.")
    st.stop()

# --- Tabs ---
tab_bal, tab_pos, tab_trades = st.tabs(["📊 Balances", "📈 Positions", "📋 Trades"])

# --- Balances tab ---
with tab_bal:
    balances = data.get("balances", [])
    if not balances:
        st.info("No balances found. Click Refresh to fetch from MEXC.")
    else:
        df_bal = pd.DataFrame(balances)
        # Ensure expected columns
        for col in ("asset", "free", "locked", "total"):
            if col not in df_bal.columns:
                df_bal[col] = 0

        # Compute USD value if price data available
        if "usd_value" not in df_bal.columns:
            df_bal["usd_value"] = None

        total_usd = df_bal["usd_value"].sum() if df_bal["usd_value"].notna().any() else 0

        # Format display
        df_display = pd.DataFrame({
            "Asset": df_bal["asset"],
            "Free": df_bal["free"].apply(lambda x: f"{float(x):,.6f}" if x else "0"),
            "Locked": df_bal["locked"].apply(lambda x: f"{float(x):,.6f}" if x else "0"),
            "Total": df_bal["total"].apply(lambda x: f"{float(x):,.6f}" if x else "0"),
            "USD Value": df_bal["usd_value"].apply(_format_usd),
        })

        if total_usd > 0:
            df_display["% of Portfolio"] = df_bal["usd_value"].apply(
                lambda x: f"{(float(x) / total_usd * 100):.1f}%" if x else "—"
            )

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            height=400,
        )
        st.caption(f"{len(balances)} assets • Total: {_format_usd(total_usd)}")

# --- Positions tab ---
with tab_pos:
    positions = data.get("positions", [])
    if not positions:
        st.info("No open positions. ")
    else:
        df_pos = pd.DataFrame(positions)
        for col in ("symbol", "side", "size", "entry_price", "mark_price", "pnl", "pnl_percent", "leverage", "liquidation_price"):
            if col not in df_pos.columns:
                df_pos[col] = None

        df_pos_display = pd.DataFrame({
            "Symbol": df_pos["symbol"],
            "Side": df_pos["side"].apply(lambda s: f"🟢 {s.upper()}" if s and s.lower() == "long" else f"🔴 {s.upper()}" if s else "—"),
            "Size": df_pos["size"].apply(lambda x: f"{float(x):,.4f}" if x else "—"),
            "Entry Price": df_pos["entry_price"].apply(_format_usd),
            "Mark Price": df_pos["mark_price"].apply(_format_usd),
            "PnL": df_pos["pnl"].apply(_format_usd),
            "PnL%": df_pos["pnl_percent"].apply(_format_pct),
            "Leverage": df_pos["leverage"].apply(lambda x: f"{float(x):.1f}x" if x else "—"),
            "Liq. Price": df_pos["liquidation_price"].apply(_format_usd),
        })

        st.dataframe(
            df_pos_display,
            use_container_width=True,
            hide_index=True,
            height=400,
        )
        st.caption(f"{len(positions)} open positions")

# --- Trades tab ---
with tab_trades:
    trades = data.get("trades", [])
    if not trades:
        st.info("No recent trades found.")
    else:
        df_tr = pd.DataFrame(trades)
        for col in ("timestamp", "symbol", "side", "type", "price", "amount", "cost", "fee", "fee_currency"):
            if col not in df_tr.columns:
                df_tr[col] = None

        df_tr_display = pd.DataFrame({
            "Time": df_tr["timestamp"].apply(lambda t: t[:19].replace("T", " ") if t else "—"),
            "Symbol": df_tr["symbol"],
            "Side": df_tr["side"].apply(lambda s: f"🟢 {s.upper()}" if s and s.lower() == "buy" else f"🔴 {s.upper()}" if s else "—"),
            "Type": df_tr["type"],
            "Price": df_tr["price"].apply(_format_usd),
            "Amount": df_tr["amount"].apply(lambda x: f"{float(x):,.6f}" if x else "—"),
            "Cost": df_tr["cost"].apply(_format_usd),
            "Fee": df_tr["fee"].apply(lambda x: f"{float(x):,.6f}" if x else "—"),
            "Fee Coin": df_tr["fee_currency"],
        })

        # Sort by time descending
        if "Time" in df_tr_display.columns:
            df_tr_display = df_tr_display.sort_values("Time", ascending=False)

        st.dataframe(
            df_tr_display,
            use_container_width=True,
            hide_index=True,
            height=400,
        )
        st.caption(f"Showing last {len(trades)} trades")
