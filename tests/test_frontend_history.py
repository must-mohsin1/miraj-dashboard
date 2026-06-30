"""Tests for history.py delete confirmation and helpers.

Run with:
    cd /Users/mustcompanymohsin/projects/miraj-dashboard
    python -m pytest tests/test_frontend_history.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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


def _noop(*args, **kwargs):
    pass


def _false(*args, **kwargs):
    return False


def _empty_str(*args, **kwargs):
    return ""


def _columns(*args, **kwargs):
    class Col:
        def __enter__(self2):
            return self2

        def __exit__(self2, *exc):
            pass

        def __call__(self2, *a, **kw):
            return self2

        def markdown(self2, *a, **kw):
            pass

        def caption(self2, *a, **kw):
            pass

        def button(self2, *a, **kw):
            return False

    # Handle both st.columns(N) and st.columns([a, b, c])
    n = len(args[0]) if isinstance(args[0], list) else args[0]
    return [Col() for _ in range(n)]


def _container(*args, **kwargs):
    class Container:
        def __enter__(self2):
            return self2

        def __exit__(self2, *exc):
            pass

    return Container()


def _form(*args, **kwargs):
    class Form:
        def __enter__(self2):
            return self2

        def __exit__(self2, *exc):
            pass

    return Form()


def _spinner(*args, **kwargs):
    class _Ctx:
        def __enter__(self2):
            return self2

        def __exit__(self2, *exc):
            pass

    return _Ctx()


streamlit_mock = MagicMock()
streamlit_mock.session_state = _SESSION_STATE
streamlit_mock.rerun = _noop
streamlit_mock.error = MagicMock()
streamlit_mock.success = _noop
streamlit_mock.warning = _noop
streamlit_mock.info = _noop
streamlit_mock.caption = _noop
streamlit_mock.markdown = _noop
streamlit_mock.spinner = _spinner
streamlit_mock.progress = _noop
streamlit_mock.page_link = _noop
streamlit_mock.stop = _noop
streamlit_mock.subheader = _noop
streamlit_mock.title = _noop
streamlit_mock.button = _false
streamlit_mock.columns = _columns
streamlit_mock.container = _container
streamlit_mock.form = _form
streamlit_mock.form_submit_button = _false
streamlit_mock.radio = _empty_str
streamlit_mock.selectbox = _empty_str
streamlit_mock.text_input = _empty_str
streamlit_mock.divider = _noop
streamlit_mock.date_input = _empty_str
streamlit_mock.slider = _empty_str
streamlit_mock.download_button = _noop
streamlit_mock.switch_page = _noop
streamlit_mock.query_params = {}

# Apply mock before any history imports
import sys

sys.modules["streamlit"] = streamlit_mock

# Pre-populate session state so module-level UI code runs safely
_SESSION_STATE["history_data"] = {
    "rows": [], "total": 0, "page": 1, "pages": 0,
}
_SESSION_STATE["history_loading"] = False
_SESSION_STATE["history_error"] = None
_SESSION_STATE["history_delete_pending_id"] = None
_SESSION_STATE["history_selected_ids"] = []
_SESSION_STATE["history_available_symbols"] = []
_SESSION_STATE["history_page"] = 1
_SESSION_STATE["history_per_page"] = 20
_SESSION_STATE["history_filter_symbol"] = "All"
_SESSION_STATE["history_filter_from"] = None
_SESSION_STATE["history_filter_to"] = None
_SESSION_STATE["history_filter_min_score"] = 0
_SESSION_STATE["history_export_dl"] = None

# Also mock is_authenticated to return True so we get past the auth guard
streamlit_mock.button.return_value = False

# Now import the history helpers
import dashboard.pages.history as history


def _reset_state():
    _SESSION_STATE.clear()
    history._HISTORY_KEY = "history_data"
    history._LOADING_KEY = "history_loading"
    history._ERROR_KEY = "history_error"
    history._DELETE_KEY = "history_delete_pending_id"
    history._SELECTED_KEY = "history_selected_ids"
    history._SYMBOLS_KEY = "history_available_symbols"
    history._PAGE_KEY = "history_page"
    history._PER_PAGE_KEY = "history_per_page"
    history._FILTER_SYMBOL_KEY = "history_filter_symbol"
    history._FILTER_FROM_KEY = "history_filter_from"
    history._FILTER_TO_KEY = "history_filter_to"
    history._FILTER_SCORE_KEY = "history_filter_min_score"
    history._EXPORT_DL_KEY = "history_export_dl"
    history._DEFAULT_PER_PAGE = 20
    history._init_state()


# ===========================================================================
# _init_state
# ===========================================================================


class TestInitState:
    def setup_method(self):
        _reset_state()

    def test_default_delete_key_is_none(self):
        assert _SESSION_STATE[history._DELETE_KEY] is None

    def test_default_selected_ids_is_empty(self):
        assert _SESSION_STATE[history._SELECTED_KEY] == []

    def test_default_loading_is_false(self):
        assert _SESSION_STATE[history._LOADING_KEY] is False

    def test_default_page_is_1(self):
        assert _SESSION_STATE[history._PAGE_KEY] == 1

    def test_init_does_not_overwrite_existing(self):
        _SESSION_STATE[history._DELETE_KEY] = 42
        history._init_state()
        assert _SESSION_STATE[history._DELETE_KEY] == 42


# ===========================================================================
# _format_dt
# ===========================================================================


class TestFormatDt:
    def test_none_returns_emdash(self):
        assert history._format_dt(None) == "—"

    def test_empty_string_returns_emdash(self):
        assert history._format_dt("") == "—"

    def test_iso_format(self):
        result = history._format_dt("2026-06-30T14:30:00Z")
        assert result == "2026-06-30 14:30"

    def test_invalid_returns_raw(self):
        assert history._format_dt("not-a-date") == "not-a-date"


# ===========================================================================
# _score_color
# ===========================================================================


class TestScoreColor:
    def test_none_returns_gray(self):
        assert history._score_color(None) == "#6b7280"

    def test_high_score_returns_green(self):
        assert history._score_color(85) == "#22c55e"
        assert history._score_color(100) == "#22c55e"

    def test_medium_score_returns_yellow(self):
        assert history._score_color(60) == "#eab308"
        assert history._score_color(50) == "#eab308"

    def test_low_score_returns_red(self):
        assert history._score_color(30) == "#ef4444"
        assert history._score_color(0) == "#ef4444"

    def test_boundary_70_is_green(self):
        assert history._score_color(70) == "#22c55e"

    def test_boundary_50_is_yellow(self):
        assert history._score_color(50) == "#eab308"

    def test_boundary_49_is_red(self):
        assert history._score_color(49) == "#ef4444"


# ===========================================================================
# _confirm_delete
# ===========================================================================


class TestConfirmDelete:
    def setup_method(self):
        _reset_state()
        _SESSION_STATE[history._DELETE_KEY] = 42
        _SESSION_STATE[history._SELECTED_KEY] = [42, 7]
        _SESSION_STATE[history._PAGE_KEY] = 1
        _SESSION_STATE[history._HISTORY_KEY] = {"rows": [], "total": 0, "page": 1, "pages": 0}
        streamlit_mock.error.reset_mock()

    @patch("dashboard.pages.history.delete_analysis")
    @patch("dashboard.pages.history.get_auth_token")
    def test_confirm_calls_delete_with_correct_args(self, mock_token, mock_delete):
        mock_token.return_value = "test-token"
        mock_delete.return_value = {"success": True}

        history._confirm_delete(42)

        mock_delete.assert_called_once_with(42, "test-token")

    @patch("dashboard.pages.history.delete_analysis")
    @patch("dashboard.pages.history.get_auth_token")
    def test_confirm_success_clears_delete_key(self, mock_token, mock_delete):
        mock_token.return_value = "test-token"
        mock_delete.return_value = {"success": True}

        history._confirm_delete(42)

        assert _SESSION_STATE[history._DELETE_KEY] is None

    @patch("dashboard.pages.history.delete_analysis")
    @patch("dashboard.pages.history.get_auth_token")
    def test_confirm_success_removes_from_selected(self, mock_token, mock_delete):
        mock_token.return_value = "test-token"
        mock_delete.return_value = {"success": True}

        history._confirm_delete(42)

        assert _SESSION_STATE[history._SELECTED_KEY] == [7]

    @patch("dashboard.pages.history.delete_analysis")
    @patch("dashboard.pages.history.get_auth_token")
    def test_confirm_no_token_shows_error(self, mock_token, mock_delete):
        mock_token.return_value = None

        history._confirm_delete(42)

        streamlit_mock.error.assert_called_once_with(
            "Session expired. Please sign in again."
        )
        mock_delete.assert_not_called()
        assert _SESSION_STATE[history._DELETE_KEY] is None

    @patch("dashboard.pages.history.delete_analysis")
    @patch("dashboard.pages.history.get_auth_token")
    def test_confirm_api_error_shows_error(self, mock_token, mock_delete):
        mock_token.return_value = "test-token"
        mock_delete.return_value = {
            "success": False,
            "error": "Server error",
        }

        history._confirm_delete(42)

        streamlit_mock.error.assert_called_once_with("Server error")
        assert _SESSION_STATE[history._DELETE_KEY] is None

    @patch("dashboard.pages.history.delete_analysis")
    @patch("dashboard.pages.history.get_auth_token")
    def test_confirm_success_calls_fetch(self, mock_token, mock_delete):
        mock_token.return_value = "test-token"
        mock_delete.return_value = {"success": True}

        with patch.object(history, "_fetch") as mock_fetch:
            history._confirm_delete(42)
            mock_fetch.assert_called_once()

    @patch("dashboard.pages.history.delete_analysis")
    @patch("dashboard.pages.history.get_auth_token")
    def test_confirm_handles_id_not_in_selected(self, mock_token, mock_delete):
        mock_token.return_value = "test-token"
        mock_delete.return_value = {"success": True}
        _SESSION_STATE[history._SELECTED_KEY] = [7, 8]

        history._confirm_delete(42)

        # Selected should be unchanged since 42 wasn't in it
        assert _SESSION_STATE[history._SELECTED_KEY] == [7, 8]
