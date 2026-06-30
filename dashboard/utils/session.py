"""
Session state management for Streamlit dashboard.

Token stored in st.session_state (survives page navigations) and
mirrored to st.query_params so the URL always carries the session.
On bare-URL navigation, query params restore the session.
"""

import json
import time
import streamlit as st
from typing import Optional


def init_session_state() -> None:
    """Initialise all session state variables."""
    if "auth_token" not in st.session_state:
        st.session_state.auth_token = None
    if "user_email" not in st.session_state:
        st.session_state.user_email = None

    # Restore from query params (survives hard refresh — URL carries session)
    if not st.session_state.auth_token:
        qt = st.query_params.get("token")
        if qt:
            st.session_state.auth_token = qt
        qe = st.query_params.get("email")
        if qe:
            st.session_state.user_email = qe

    # If authenticated, ensure query params are present so refresh works
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
    """Persist JWT to session state and query params."""
    st.session_state.auth_token = token
    if email:
        st.session_state.user_email = email
    st.query_params["token"] = token
    if email:
        st.query_params["email"] = email


def get_auth_token() -> Optional[str]:
    """Return current JWT or None."""
    return st.session_state.get("auth_token")


def get_user_email() -> Optional[str]:
    """Return logged-in user's email or None."""
    return st.session_state.get("user_email")


def logout() -> None:
    """Clear auth state and query params."""
    st.session_state.auth_token = None
    st.session_state.user_email = None
    st.query_params.clear()
