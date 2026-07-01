"""
Crypto Analysis App — Streamlit Dashboard Entry Point

Auth gate at the top.  Unauthenticated users see a centred login /
register form.  Authenticated users get a sidebar navigation built via
``st.navigation`` (replaces Streamlit's auto-discovered page list).

Page-level auth guards in ``pages/*.py`` are still applied for defence
in depth against direct URL access.
"""

import os
import sys

# Ensure the dashboard package is importable when run via streamlit
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

import streamlit as st

from dashboard.utils.api_client import login as api_login, register as api_register, set_base_url
from dashboard.utils.session import (
    get_user_email,
    init_session_state,
    is_authenticated,
    logout,
    set_auth_token,
)

# ---------------------------------------------------------------------------
# Page config — MUST be the first Streamlit command
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Crypto Analysis",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="auto",
)

init_session_state()

# Use API_BASE_URL from environment if set (Docker), otherwise default localhost
_api_base = os.environ.get("API_BASE_URL", "")
if _api_base:
    set_base_url(_api_base)


def _trigger_browser_cookie(token: str, email: str) -> None:
    """Set auth_session cookie directly from JavaScript using the token.
    Cookie is non-HttpOnly so JS can read it for session restore.
    """
    import json as _json
    safe_token = _json.dumps(token)
    st.html(f"""
    <img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" onload="
    (function() {{
        var d = new Date();
        d.setTime(d.getTime() + (60 * 60 * 1000));
        var expires = 'expires=' + d.toUTCString();
        document.cookie = 'auth_session=' + {safe_token} + ';' + expires + ';path=/;SameSite=Lax';
    }})();
    " />
    """)

# ---------------------------------------------------------------------------
# Login / Register page (unauthenticated)
# ---------------------------------------------------------------------------


def _render_auth_page() -> None:
    """Centred sign-in and registration forms."""
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.image(
            "https://img.icons8.com/fluency/96/000000/cryptocurrency.png",
            width=80,
        )
        st.markdown("# Crypto Analysis")
        st.markdown("##### Market intelligence & trading signals")

        tab_login, tab_register = st.tabs(["Sign In", "Create Account"])

        # ---- Sign In ----
        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="you@example.com")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button(
                    "Sign In", type="primary", use_container_width=True
                )

            if submitted:
                if not email or not password:
                    st.error("Please enter both email and password.")
                else:
                    with st.spinner("Signing in…"):
                        result = api_login(email, password)
                    if result["success"]:
                        set_auth_token(result["token"], email=email)
                        # Inject JS to call login endpoint from browser
                        # so Set-Cookie header reaches the browser
                        _trigger_browser_cookie(result["token"], email)
                        st.success("Login successful!")
                        st.rerun()
                    else:
                        st.error(result["error"])

        # ---- Create Account ----
        with tab_register:
            with st.form("register_form"):
                reg_email = st.text_input(
                    "Email", placeholder="you@example.com", key="reg_email"
                )
                reg_password = st.text_input(
                    "Password",
                    type="password",
                    help="Minimum 8 characters",
                    key="reg_password",
                )
                reg_confirm = st.text_input(
                    "Confirm Password", type="password", key="reg_confirm"
                )
                submitted_reg = st.form_submit_button(
                    "Create Account", use_container_width=True
                )

            if submitted_reg:
                if not reg_email or not reg_password:
                    st.error("Please fill in all fields.")
                elif reg_password != reg_confirm:
                    st.error("Passwords do not match.")
                elif len(reg_password) < 8:
                    st.error("Password must be at least 8 characters.")
                else:
                    with st.spinner("Creating account…"):
                        result = api_register(reg_email, reg_password)
                    if result["success"]:
                        st.success("Account created! Sign in above.")
                    else:
                        st.error(result["error"])


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

if not is_authenticated():
    _render_auth_page()
    st.stop()

# ---------------------------------------------------------------------------
# Authenticated — sidebar navigation + logout
# ---------------------------------------------------------------------------

# st.navigation replaces the auto-discovered page sidebar.
# The homepage content lives in a dedicated home page.
nav = st.navigation(
    {
        "Home": [
            st.Page("pages/home.py", title="Home", icon="🏠"),
        ],
        "Analysis": [
            st.Page("pages/macro.py", title="Macro Dashboard", icon="📈"),
            st.Page("pages/scanner.py", title="Scanner", icon="🔍"),
            st.Page("pages/analysis.py", title="Analysis", icon="📋"),
        ],
        "Portfolio": [
            st.Page("pages/portfolio.py", title="Portfolio", icon="💼"),
        ],
        "History & Settings": [
            st.Page("pages/history.py", title="History", icon="📜"),
            st.Page("pages/settings.py", title="Settings", icon="⚙️"),
        ],
    },
    position="sidebar",
)

# Render navigation first, then add sidebar footer below it.
# This ordering ensures the logout button's widget position is stable
# and its event handler fires correctly on every page.
nav.run()

with st.sidebar:
    st.markdown(f"Signed in as **{get_user_email() or '—'}**")
    st.divider()
    if st.button("🚪 Logout", use_container_width=True, type="secondary"):
        logout()
        st.rerun()
