"""
History — placeholder page.

Browse past analyses and saved scans.
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

st.title("📜 History")
st.markdown("Browse your past scans and saved analyses.")

st.info("ℹ️ Analysis history will populate once the backend API is connected.", icon="ℹ️")

st.markdown("---")
st.subheader("Saved Analyses")
st.caption("No saved analyses yet.")
