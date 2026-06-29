"""
Scanner — placeholder page.

Search and scan trading pairs for confluence-based analysis.
"""

import streamlit as st

from dashboard.utils.session import is_authenticated

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

st.title("🔍 Scanner")
st.markdown("Search for a trading pair and run a full confluence analysis.")

symbol = st.text_input("Trading Pair", value="BTC-USD", placeholder="e.g. BTC-USD, ETH-USD")

col1, col2 = st.columns([1, 4])

with col1:
    run_scan = st.button("Run Analysis", type="primary", use_container_width=True)

with col2:
    st.caption("Triggers a multi-timeframe analysis pipeline (≈60 s).")

if run_scan:
    st.info("ℹ️ Analysis will be available once the backend scan API is connected.", icon="ℹ️")

st.markdown("---")
st.subheader("Recent Scans")
st.caption("No scans yet.")
