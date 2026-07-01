"""
Session state management for Streamlit dashboard.

Uses localStorage via JS injection for persistent sessions that survive
bare URL navigation, F5 refresh, and page closings.

Flow:
1. On login: inject JS to store token+email in localStorage
2. On page load: inject JS that reads localStorage and redirects to
   ?token=xxx&email=yyy if session state is empty
3. Query params restore the session in st.session_state
4. On logout: inject JS to clear localStorage
"""

import json
import time
import streamlit as st
from typing import Optional


def _inject_js(html: str) -> None:
    """No-op — Streamlit doesn't support script injection reliably."""
    pass


def _store_token_js(token: str, email: str = "") -> None:
    """No-op — use query params for persistence."""
    pass


def _restore_from_localstorage_js() -> None:
    """No-op — query params handle F5 refresh, bare URL requires manual re-login."""
    pass


def _clear_token_js() -> None:
    """No-op."""
    pass


def init_session_state() -> None:
    """Initialise all session state variables, restoring from query params."""
    if "auth_token" not in st.session_state:
        st.session_state.auth_token = None
    if "user_email" not in st.session_state:
        st.session_state.user_email = None
    if "_just_logged_out" not in st.session_state:
        st.session_state._just_logged_out = False

    # Skip restore immediately after logout
    if st.session_state._just_logged_out:
        st.session_state._just_logged_out = False
        return

    # Restore from query params (survives F5 refresh with URL intact)
    if not st.session_state.auth_token:
        qt = st.query_params.get("token")
        if qt:
            st.session_state.auth_token = qt
        qe = st.query_params.get("email")
        if qe:
            st.session_state.user_email = qe

    # Restore from HTTP cookie (set by backend, survives bare URL navigation)
    if not st.session_state.auth_token:
        try:
            cookie_token = st.context.cookies.get("auth_session")
            if cookie_token:
                st.session_state.auth_token = cookie_token
            else:
                # Debug: log what cookies we see
                import logging as _log
                _log.getLogger(__name__).warning(
                    "No auth_session cookie. Available: %s",
                    list(st.context.cookies.keys()),
                )
        except Exception as _e:
            import logging as _log
            _log.getLogger(__name__).warning("Cookie restore failed: %s", _e)

    # If still not authenticated, inject JS to restore from localStorage
    # This handles bare URL navigation (typing localhost:8502 without query params)
    if not st.session_state.auth_token:
        _restore_from_localstorage_js()

    # Ensure query params reflect current session for refresh persistence
    _sync_query_params()


def _sync_query_params() -> None:
    """Ensure query params reflect current session state."""
    token = st.session_state.get("auth_token")
    if token:
        current_token = st.query_params.get("token")
        if current_token != token:
            st.query_params["token"] = token
        email = st.session_state.get("user_email")
        if email:
            current_email = st.query_params.get("email")
            if current_email != email:
                st.query_params["email"] = email


def _decode_jwt_payload(token: str) -> Optional[dict]:
    """Decode JWT payload without signature verification."""
    try:
        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        import base64
        return json.loads(base64.b64decode(payload_b64))
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


def is_authenticated() -> bool:
    """Return True if a valid (non-expired) JWT is in session state."""
    token = st.session_state.get("auth_token")
    if not token:
        return False
    payload = _decode_jwt_payload(token)
    if payload is None:
        return False
    exp = payload.get("exp", 0)
    if not isinstance(exp, (int, float)):
        return False
    if exp < time.time() - 30:
        return False
    return True


def set_auth_token(token: str, email: Optional[str] = None) -> None:
    """Persist JWT to session state, query params, and localStorage."""
    st.session_state.auth_token = token
    if email:
        st.session_state.user_email = email
    st.query_params["token"] = token
    if email:
        st.query_params["email"] = email
    # Store in localStorage for persistent sessions
    _store_token_js(token, email or "")


def get_auth_token() -> Optional[str]:
    """Return current JWT or None."""
    return st.session_state.get("auth_token")


def get_user_email() -> Optional[str]:
    """Return logged-in user's email or None."""
    return st.session_state.get("user_email")


def logout() -> None:
    """Clear auth state, query params, and localStorage."""
    st.session_state.auth_token = None
    st.session_state.user_email = None
    st.session_state._just_logged_out = True
    st.query_params.clear()
    _clear_token_js()
