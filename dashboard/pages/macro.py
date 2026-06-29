"""
Macro Dashboard — displays live macro market data cards.

Data flow
---------
1. Page mount / reload → GET /api/v1/macro via get_macro(token)
2. On success → render_macro_cards(data) with the API response payload
3. On error → render_error_state(error_msg)
4. On empty → render_empty_state()
"""

from __future__ import annotations

import streamlit as st

from dashboard.components.macro_cards import (
    render_empty_state,
    render_error_state,
    render_macro_cards,
)
from dashboard.utils.api_client import get_macro
from dashboard.utils.session import get_auth_token, is_authenticated

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------
if not is_authenticated():
    st.warning("Please sign in to access this page.")
    st.page_link("app.py", label="Go to Sign In")
    st.stop()

# ---------------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------------

st.title("📈 Macro Dashboard")
st.markdown("Market-wide macro indicators at a glance.")

token = get_auth_token()
if not token:
    render_error_state("Session expired. Please sign in again.")
    st.stop()

with st.spinner("Loading macro data…"):
    result = get_macro(token)

if result.get("success"):
    data = result.get("data", {})
    # The backend wraps macro payload; extract from nested response if needed
    payload = data if isinstance(data, dict) else {}
    if payload:
        render_macro_cards(payload)
    else:
        render_empty_state()
else:
    render_error_state(result.get("error", "Unknown error"))
