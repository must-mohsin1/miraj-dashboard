"""
Session state management for Streamlit dashboard.

Handles JWT token storage, expiry checking, and logout.
Token is stored in st.session_state (survives page navigations) and
restored from query params on full page refresh.
"""

import json
import time
import streamlit as st
from typing import Optional


def init_session_state() -> None:
    """Initialise all session state variables on first run, restoring from query params if available."""
    if "auth_token" not in st.session_state:
        st.session_state.auth_token = None
    if "user_email" not in st.session_state:
        st.session_state.user_email = None

    # Restore from query params if available (survives hard refresh)
    if not st.session_state.auth_token:
        qt = st.query_params.get("token")
        if qt:
            st.session_state.auth_token = qt
        qe = st.query_params.get("email")
        if qe:
            st.session_state.user_email = qe


def _decode_jwt_payload(token: str) -> Optional[dict]:
    """
    Decode the JWT payload *without* verifying the signature.

    This is a client-side convenience for checking the ``exp`` claim.
    The server is the single source of truth for token validity.
    """
    try:
        payload_b64 = token.split(".")[1]
        # Restore padding stripped by URL-safe base64
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        import base64

        return json.loads(base64.b64decode(payload_b64))
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


def is_authenticated() -> bool:
    """
    Return ``True`` if a valid (non-expired) JWT is in session state.

    Quick client-side expiry check avoids waiting for a 401 on every
    page load.  Actual auth enforcement still happens server-side.
    """
    token = st.session_state.get("auth_token")
    if not token:
        return False

    payload = _decode_jwt_payload(token)
    if payload is None:
        return False

    exp = payload.get("exp", 0)
    if not isinstance(exp, (int, float)):
        return False

    # Allow 30 s leeway for clock skew
    if exp < time.time() - 30:
        return False

    return True


def set_auth_token(token: str, email: Optional[str] = None) -> None:
    """Persist the JWT (and optionally the user email) to session state."""
    st.session_state.auth_token = token
    if email:
        st.session_state.user_email = email

    # Set query params to token+email so they survive a hard refresh
    st.query_params["token"] = token
    if email:
        st.query_params["email"] = email


def get_auth_token() -> Optional[str]:
    """Return the current JWT, or ``None`` if not authenticated."""
    return st.session_state.get("auth_token")


def get_user_email() -> Optional[str]:
    """Return the logged-in user's email, or ``None``."""
    return st.session_state.get("user_email")


def logout() -> None:
    """Clear auth state — effectively logs the user out."""
    st.session_state.auth_token = None
    st.session_state.user_email = None
    # Clear query params
    st.query_params.clear()
