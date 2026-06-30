"""Tests for session.py auth state management.

Run with:
    cd /Users/mustcompanymohsin/projects/miraj-dashboard
    python3 -m pytest tests/test_session.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import time
from typing import Optional


# ---------------------------------------------------------------------------
# Streamlit mock — mirrors the pattern in test_frontend_settings.py
# ---------------------------------------------------------------------------

class SessionState(dict):
    """A dict that also supports attribute-style access like streamlit's session_state."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)


_SESSION_STATE = SessionState()


class QueryParamProxy(dict):
    """Mocks st.query_params as a dict-like object."""

    def clear(self):
        dict.clear(self)


_QUERY_PARAMS = QueryParamProxy()


class CookieProxy(dict):
    """Mocks st.context.cookies as a dict-like object.

    Supports get, set by key, and deletion (with KeyError on missing key).
    """

    def clear(self):
        dict.clear(self)


_COOKIES = CookieProxy()


def _noop(*args, **kwargs):
    pass


streamlit_mock = MagicMock()
streamlit_mock.session_state = _SESSION_STATE
streamlit_mock.rerun = _noop
streamlit_mock.error = _noop
streamlit_mock.success = _noop
streamlit_mock.warning = _noop
streamlit_mock.info = _noop
streamlit_mock.caption = _noop
streamlit_mock.markdown = _noop
streamlit_mock.spinner = _noop
streamlit_mock.progress = _noop
streamlit_mock.page_link = _noop
streamlit_mock.stop = _noop
streamlit_mock.subheader = _noop
streamlit_mock.title = _noop
streamlit_mock.button = _false = lambda *a, **kw: False
streamlit_mock.columns = _noop
streamlit_mock.container = _noop
streamlit_mock.form = _noop
streamlit_mock.form_submit_button = _noop
streamlit_mock.text_input = _noop
streamlit_mock.divider = _noop
streamlit_mock.expander = _noop

# Wire query_params and context.cookies as PropertyMocks
type(streamlit_mock).query_params = PropertyMock(return_value=_QUERY_PARAMS)
type(streamlit_mock).context = PropertyMock(return_value=MagicMock(cookies=_COOKIES))

# Apply mock before any session imports
import sys
import importlib
sys.modules["streamlit"] = streamlit_mock

# If the session module was already imported by another test file,
# force-reload with the correct mock
if "dashboard.utils.session" in sys.modules:
    importlib.reload(sys.modules["dashboard.utils.session"])

# Now import the module under test
import dashboard.utils.session as session


def _reset_state():
    _SESSION_STATE.clear()
    _QUERY_PARAMS.clear()
    _COOKIES.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInitSessionState:
    def test_initialises_defaults(self):
        _reset_state()
        assert "auth_token" not in _SESSION_STATE
        assert "user_email" not in _SESSION_STATE

        session.init_session_state()

        assert _SESSION_STATE.get("auth_token") is None
        assert _SESSION_STATE.get("user_email") is None
        assert _SESSION_STATE.get("_just_logged_out") is False

    def test_restores_from_query_params_on_fresh_session(self):
        _reset_state()
        _QUERY_PARAMS["token"] = "test-jwt"
        _QUERY_PARAMS["email"] = "user@test.com"

        session.init_session_state()

        assert _SESSION_STATE["auth_token"] == "test-jwt"
        assert _SESSION_STATE["user_email"] == "user@test.com"

    def test_does_not_restore_from_query_params_when_logged_out(self):
        _reset_state()
        # Simulate: user logged out -> _just_logged_out is True
        _SESSION_STATE["_just_logged_out"] = True
        # Stale query params from previous session
        _QUERY_PARAMS["token"] = "stale-jwt"
        _QUERY_PARAMS["email"] = "old@test.com"

        session.init_session_state()

        # Should NOT restore from stale query params
        assert _SESSION_STATE.get("auth_token") is None
        assert _SESSION_STATE.get("user_email") is None
        # Flag should be cleared after this run
        assert _SESSION_STATE["_just_logged_out"] is False

    def test_restores_on_subsequent_run_after_cleared_flag(self):
        _reset_state()
        # First run: _just_logged_out is True from a prior logout
        _SESSION_STATE["_just_logged_out"] = True
        _QUERY_PARAMS["token"] = "stale-jwt"

        session.init_session_state()
        # auth_token is still None because flag prevented restore
        assert _SESSION_STATE.get("auth_token") is None

        # Second run: flag is cleared, token still in query params
        # (simulates st.query_params.clear() not taking effect on first run)
        session.init_session_state()
        assert _SESSION_STATE["auth_token"] == "stale-jwt"

    # ---- Cookie restore tests ----

    def test_restores_from_cookie_on_bare_url(self):
        """Cookie restores the session when there are no query params (bare URL)."""
        _reset_state()
        _COOKIES["auth_session"] = "cookie-jwt"

        session.init_session_state()

        assert _SESSION_STATE["auth_token"] == "cookie-jwt"

    def test_cookie_takes_priority_over_query_params(self):
        """When both cookie and query params exist, cookie wins."""
        _reset_state()
        _COOKIES["auth_session"] = "cookie-jwt"
        _QUERY_PARAMS["token"] = "param-jwt"
        _QUERY_PARAMS["email"] = "param@test.com"

        session.init_session_state()

        # Cookie should be used, not query params
        assert _SESSION_STATE["auth_token"] == "cookie-jwt"
        # Email should also be None because query params skipped
        assert _SESSION_STATE.get("user_email") is None

    def test_does_not_restore_from_cookie_when_logged_out(self):
        """_just_logged_out flag prevents cookie restore."""
        _reset_state()
        _SESSION_STATE["_just_logged_out"] = True
        _COOKIES["auth_session"] = "stale-cookie-jwt"

        session.init_session_state()

        assert _SESSION_STATE.get("auth_token") is None
        assert _SESSION_STATE["_just_logged_out"] is False


class TestSetAuthToken:
    def test_sets_session_state(self):
        _reset_state()
        session.init_session_state()

        session.set_auth_token("my-token", email="me@test.com")

        assert _SESSION_STATE["auth_token"] == "my-token"
        assert _SESSION_STATE["user_email"] == "me@test.com"

    def test_sets_query_params(self):
        _reset_state()
        session.init_session_state()

        session.set_auth_token("token-val", email="e@t.com")

        assert _QUERY_PARAMS.get("token") == "token-val"
        assert _QUERY_PARAMS.get("email") == "e@t.com"

    def test_sets_cookie(self):
        """set_auth_token also persists the token as an HTTP cookie."""
        _reset_state()
        session.init_session_state()

        session.set_auth_token("token-val", email="e@t.com")

        assert _COOKIES.get("auth_session") == "token-val"

    def test_email_optional(self):
        _reset_state()
        session.init_session_state()

        session.set_auth_token("just-token")

        assert _SESSION_STATE["auth_token"] == "just-token"
        assert _SESSION_STATE.get("user_email") is None
        assert "email" not in _QUERY_PARAMS


class TestLogout:
    def setup_method(self):
        _reset_state()
        session.init_session_state()
        # Simulate logged in state
        session.set_auth_token("my-token", email="user@test.com")

    def test_clears_session_state(self):
        assert _SESSION_STATE["auth_token"] == "my-token"

        session.logout()

        assert _SESSION_STATE.get("auth_token") is None
        assert _SESSION_STATE.get("user_email") is None

    def test_sets_just_logged_out_flag(self):
        assert not _SESSION_STATE.get("_just_logged_out")

        session.logout()

        assert _SESSION_STATE["_just_logged_out"] is True

    def test_clears_query_params(self):
        assert "token" in _QUERY_PARAMS

        session.logout()

        assert "token" not in _QUERY_PARAMS
        assert "email" not in _QUERY_PARAMS

    def test_clears_cookie(self):
        """Logout clears the HTTP cookie."""
        assert "auth_session" in _COOKIES

        session.logout()

        assert "auth_session" not in _COOKIES

    def test_logout_then_init_does_not_restore(self):
        """End-to-end: logout + rerun should not restore stale auth."""
        # Populate query params (they were set by set_auth_token)
        _QUERY_PARAMS["token"] = "stale-jwt"
        _QUERY_PARAMS["email"] = "old@test.com"
        _COOKIES["auth_session"] = "stale-cookie-jwt"

        session.logout()

        # Simulate the next script run's init
        session.init_session_state()

        # Despite stale query params and cookie, auth should remain None
        assert _SESSION_STATE.get("auth_token") is None
        assert _SESSION_STATE.get("user_email") is None

    def test_login_after_logout_works(self):
        """After logout, a fresh login should set new state correctly."""
        session.logout()
        session.init_session_state()

        session.set_auth_token("new-token", email="new@test.com")

        assert _SESSION_STATE["auth_token"] == "new-token"
        assert _SESSION_STATE["user_email"] == "new@test.com"
        assert _QUERY_PARAMS.get("token") == "new-token"
        assert _QUERY_PARAMS.get("email") == "new@test.com"
        assert _COOKIES.get("auth_session") == "new-token"


class TestIsAuthenticated:
    def setup_method(self):
        _reset_state()
        session.init_session_state()

    def test_false_when_no_token(self):
        assert not session.is_authenticated()

    def test_false_when_token_is_none(self):
        _SESSION_STATE["auth_token"] = None
        assert not session.is_authenticated()

    def test_false_when_expired(self):
        # Create a token that expired 10 seconds ago
        import base64, json
        expired_payload = base64.urlsafe_b64encode(
            json.dumps({"exp": time.time() - 40}).encode()
        ).rstrip(b"=").decode()
        _SESSION_STATE["auth_token"] = f"header.{expired_payload}.sig"

        # _decode_jwt_payload expects standard base64, not URL-safe
        # Let's just test that expired tokens are rejected
        assert not session.is_authenticated()

    def test_true_with_valid_token(self):
        # Create a token valid for 1 hour from now
        import base64, json
        future_payload = base64.urlsafe_b64encode(
            json.dumps({"exp": time.time() + 3600}).encode()
        ).rstrip(b"=").decode()
        _SESSION_STATE["auth_token"] = f"header.{future_payload}.sig"

        assert session.is_authenticated()

    def test_false_with_garbage_token(self):
        _SESSION_STATE["auth_token"] = "not-a-real-token"
        assert not session.is_authenticated()
