"""
Home page — welcome dashboard shown after login.
"""

import streamlit as st

from dashboard.utils.session import is_authenticated

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------
if not is_authenticated():
    st.switch_page("app.py")

# ---------------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------------

st.title("🏠 Dashboard Home")

col_welcome, col_quick = st.columns([3, 2])

with col_welcome:
    st.markdown(
        """
        Welcome to **Crypto Analysis** — your comprehensive market intelligence
        platform powered by multi-timeframe technical analysis.

        ### Getting started
        1. **📈 Macro Dashboard** — View BTC dominance, DXY, Fear & Greed, and regime signals.
        2. **🔍 Scanner** — Scan any trading pair for confluence-based analysis.
        3. **📋 Analysis** — Review detailed analysis with charts, score breakdowns, and trade plans.
        4. **📜 History** — Browse past scans and saved analyses.
        """
    )

with col_quick:
    st.markdown("### Quick Actions")
    if st.button("📈 Open Macro Dashboard", use_container_width=True):
        st.switch_page("pages/macro.py")
    if st.button("🔍 Scan a Pair", use_container_width=True):
        st.switch_page("pages/scanner.py")
