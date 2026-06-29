"""Tests for settings.py watchlist helpers.

Run with:
    cd /Users/mustcompanymohsin/projects/miraj-dashboard
    python -m pytest tests/test_frontend_settings.py -v
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
    return [Col() for _ in range(args[0])]

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

def _expander(*args, **kwargs):
    class Expander:
        def __enter__(self2):
            return self2
        def __exit__(self2, *exc):
            pass
    return Expander()

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
streamlit_mock.error = _noop
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
streamlit_mock.expander = _expander

# Apply mock before any settings imports
import sys
sys.modules["streamlit"] = streamlit_mock

# Now import the settings helpers
import dashboard.pages.settings as settings


def _reset_state():
    _SESSION_STATE.clear()
    settings._WL_KEY = "watchlist_pairs"
    settings._WL_PREV_KEY = "watchlist_original"
    settings._WL_LOADED_KEY = "watchlist_loaded"
    settings._WL_LOADING_KEY = "watchlist_loading"
    settings._WL_ERROR_KEY = "watchlist_error"
    settings._CONFIRM_KEY = "watchlist_confirm_remove"
    settings._CONFIRM_PAIR_KEY = "watchlist_confirm_pair"
    # Re-init state
    settings._init_state()


class TestIsValidPair:
    def test_valid_dash_format(self):
        assert settings._is_valid_pair("BTC-USD")

    def test_valid_concat_format(self):
        assert settings._is_valid_pair("BTCUSDT")

    def test_too_short(self):
        assert not settings._is_valid_pair("AB")

    def test_empty(self):
        assert not settings._is_valid_pair("")

    def test_whitespace(self):
        assert not settings._is_valid_pair("   ")


class TestIsDirty:
    def setup_method(self):
        _reset_state()
        _SESSION_STATE[settings._WL_KEY] = [
            {"id": 1, "pair": "BTC-USD", "sort_order": 0},
            {"id": 2, "pair": "ETH-USD", "sort_order": 1},
        ]
        _SESSION_STATE[settings._WL_PREV_KEY] = [
            {"id": 1, "pair": "BTC-USD", "sort_order": 0},
            {"id": 2, "pair": "ETH-USD", "sort_order": 1},
        ]

    def test_not_dirty_when_unchanged(self):
        assert not settings._is_dirty()

    def test_dirty_when_reordered(self):
        pairs = _SESSION_STATE[settings._WL_KEY]
        pairs[0], pairs[1] = pairs[1], pairs[0]
        pairs[0]["sort_order"] = 0
        pairs[1]["sort_order"] = 1
        assert settings._is_dirty()

    def test_dirty_when_pair_removed(self):
        _SESSION_STATE[settings._WL_KEY] = [
            {"id": 1, "pair": "BTC-USD", "sort_order": 0},
        ]
        assert settings._is_dirty()

    def test_dirty_when_pair_added(self):
        _SESSION_STATE[settings._WL_KEY] = [
            {"id": 1, "pair": "BTC-USD", "sort_order": 0},
            {"id": 2, "pair": "ETH-USD", "sort_order": 1},
            {"id": 3, "pair": "SOL-USD", "sort_order": 2},
        ]
        assert settings._is_dirty()


class TestMovePair:
    def setup_method(self):
        _reset_state()
        _SESSION_STATE[settings._WL_KEY] = [
            {"id": 1, "pair": "BTC-USD", "sort_order": 0},
            {"id": 2, "pair": "ETH-USD", "sort_order": 1},
            {"id": 3, "pair": "SOL-USD", "sort_order": 2},
        ]

    def test_move_up(self):
        settings._move_pair(1, -1)
        pairs = _SESSION_STATE[settings._WL_KEY]
        assert pairs[0]["pair"] == "ETH-USD"
        assert pairs[1]["pair"] == "BTC-USD"
        assert pairs[2]["pair"] == "SOL-USD"
        assert all(p["sort_order"] == i for i, p in enumerate(pairs))

    def test_move_down(self):
        settings._move_pair(0, 1)
        pairs = _SESSION_STATE[settings._WL_KEY]
        assert pairs[0]["pair"] == "ETH-USD"
        assert pairs[1]["pair"] == "BTC-USD"
        assert pairs[2]["pair"] == "SOL-USD"
        assert all(p["sort_order"] == i for i, p in enumerate(pairs))

    def test_no_move_at_top(self):
        settings._move_pair(0, -1)
        pairs = _SESSION_STATE[settings._WL_KEY]
        assert pairs[0]["pair"] == "BTC-USD"

    def test_no_move_at_bottom(self):
        settings._move_pair(2, 1)
        pairs = _SESSION_STATE[settings._WL_KEY]
        assert pairs[2]["pair"] == "SOL-USD"

    def test_sort_order_updated(self):
        settings._move_pair(0, 1)
        pairs = _SESSION_STATE[settings._WL_KEY]
        for i, p in enumerate(pairs):
            assert p["sort_order"] == i, f"Expected sort_order {i} for {p['pair']}, got {p['sort_order']}"


class TestRemovePair:
    @patch("dashboard.pages.settings.remove_watchlist_pair")
    @patch("dashboard.pages.settings.get_auth_token")
    def test_remove_calls_api_with_id(
        self, mock_token, mock_remove
    ):
        _reset_state()
        mock_token.return_value = "test-token"
        mock_remove.return_value = {"success": True}

        settings._remove_pair(42, "BTC-USD")

        mock_remove.assert_called_once_with(42, "test-token")

    @patch("dashboard.pages.settings.remove_watchlist_pair")
    @patch("dashboard.pages.settings.get_auth_token")
    def test_remove_clears_confirm_state(
        self, mock_token, mock_remove
    ):
        _reset_state()
        mock_token.return_value = "test-token"
        mock_remove.return_value = {"success": True}
        _SESSION_STATE[settings._CONFIRM_KEY] = 42
        _SESSION_STATE[settings._CONFIRM_PAIR_KEY] = "BTC-USD"

        settings._remove_pair(42, "BTC-USD")

        assert _SESSION_STATE[settings._CONFIRM_KEY] is None
        assert _SESSION_STATE[settings._CONFIRM_PAIR_KEY] == ""


class TestSaveOrder:
    @patch("dashboard.pages.settings.reorder_watchlist")
    @patch("dashboard.pages.settings.get_auth_token")
    def test_save_sends_pair_ids_in_order(
        self, mock_token, mock_reorder
    ):
        _reset_state()
        mock_token.return_value = "test-token"
        mock_reorder.return_value = {"success": True}
        _SESSION_STATE[settings._WL_KEY] = [
            {"id": 1, "pair": "ETH-USD", "sort_order": 0},
            {"id": 2, "pair": "BTC-USD", "sort_order": 1},
            {"id": 3, "pair": "SOL-USD", "sort_order": 2},
        ]

        settings._save_order()

        mock_reorder.assert_called_once_with(
            [1, 2, 3], "test-token"
        )

    @patch("dashboard.pages.settings.reorder_watchlist")
    @patch("dashboard.pages.settings.get_auth_token")
    def test_save_updates_prev_snapshot(
        self, mock_token, mock_reorder
    ):
        _reset_state()
        mock_token.return_value = "test-token"
        mock_reorder.return_value = {"success": True}
        _SESSION_STATE[settings._WL_KEY] = [
            {"id": 1, "pair": "BTC-USD", "sort_order": 0},
        ]

        settings._save_order()

        # The prev key should be a deep copy of current pairs
        assert _SESSION_STATE[settings._WL_PREV_KEY] == [
            {"id": 1, "pair": "BTC-USD", "sort_order": 0}
        ]


class TestSeedDefaultPairs:
    @patch("dashboard.pages.settings.add_watchlist_pair")
    @patch("dashboard.pages.settings.get_auth_token")
    def test_skips_existing_pairs(
        self, mock_token, mock_add
    ):
        _reset_state()
        mock_token.return_value = "test-token"
        mock_add.return_value = {"success": True}
        _SESSION_STATE[settings._WL_KEY] = [
            {"pair": "BTC-USD", "sort_order": 0},
        ]

        settings._seed_default_pairs()

        # Should not try to add BTC-USD again
        calls = [c[0][0] for c in mock_add.call_args_list]
        assert "BTC-USD" not in calls, "Should skip existing pairs"
        assert len(calls) <= 14  # At most 14 new pairs (15 default - 1 existing)

    @patch("dashboard.pages.settings.add_watchlist_pair")
    @patch("dashboard.pages.settings.get_auth_token")
    def test_adds_missing_pairs(
        self, mock_token, mock_add
    ):
        _reset_state()
        mock_token.return_value = "test-token"
        mock_add.return_value = {"success": True}
        _SESSION_STATE[settings._WL_KEY] = []

        settings._seed_default_pairs()

        # Should add all 15 default pairs
        default_symbols = set(settings.DEFAULT_PAIRS)
        called_symbols = set(c[0][0] for c in mock_add.call_args_list)
        assert called_symbols == default_symbols


class TestFetchWatchlist:
    @patch("dashboard.pages.settings.get_watchlist")
    @patch("dashboard.pages.settings.get_auth_token")
    def test_handles_bare_list_response(
        self, mock_token, mock_get
    ):
        _reset_state()
        mock_token.return_value = "test-token"
        mock_get.return_value = {
            "success": True,
            "data": [
                {"id": 1, "pair": "BTC-USD", "sort_order": 0, "score": None, "status": "Active"},
                {"id": 2, "pair": "ETH-USD", "sort_order": 1, "score": 72, "status": "Active"},
            ],
        }

        settings._fetch_watchlist()

        pairs = _SESSION_STATE[settings._WL_KEY]
        assert len(pairs) == 2
        assert pairs[0]["pair"] == "BTC-USD"
        assert pairs[1]["pair"] == "ETH-USD"

    @patch("dashboard.pages.settings.get_watchlist")
    @patch("dashboard.pages.settings.get_auth_token")
    def test_handles_error_response(
        self, mock_token, mock_get
    ):
        _reset_state()
        mock_token.return_value = "test-token"
        mock_get.return_value = {
            "success": False,
            "error": "Failed to fetch watchlist",
        }

        settings._fetch_watchlist()

        assert _SESSION_STATE[settings._WL_ERROR_KEY] == "Failed to fetch watchlist"
        assert _SESSION_STATE[settings._WL_LOADING_KEY] is False
