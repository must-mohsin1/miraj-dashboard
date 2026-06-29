"""
Settings — placeholder page.

User preferences, API URL configuration, and account management.
"""

import streamlit as st

from dashboard.utils.api_client import set_base_url
from dashboard.utils.session import get_user_email, is_authenticated, logout

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

st.title("⚙️ Settings")

user_email = get_user_email() or "—"

st.markdown(f"**Account:** {user_email}")

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
