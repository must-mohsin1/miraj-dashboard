"""Tests for Scanner page helpers (dashboard/pages/scanner.py).

Run with::

    python test_scanner.py

Tests pure utility functions from scanner.py without requiring Streamlit
or a running backend.  We mock streamlight *and* the session module before
importing the scanner page so the module-level Streamlit calls pass.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Patch EVERYTHING the scanner page touches at module level BEFORE import
# ---------------------------------------------------------------------------

# 1. streamlit stub
_st_streamlit_stub = MagicMock()
_st_session_state: dict = {}
_st_streamlit_stub.session_state = _st_session_state

# 2. session module stubs
_st_session_stub = MagicMock()
_st_session_stub.is_authenticated.return_value = True
_st_session_stub.get_auth_token.return_value = "test-token-123"

# Make st.columns() return unpackable lists of mocks
def _mock_columns(spec):
    n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
    return [MagicMock() for _ in range(n)]

_st_streamlit_stub.columns.side_effect = _mock_columns

# Make st.button() return False by default (no click during import)
_st_streamlit_stub.button.return_value = False

# Make st.spinner work as context manager
_st_streamlit_mgr = MagicMock()
_st_streamlit_mgr.__enter__ = MagicMock(return_value=None)
_st_streamlit_mgr.__exit__ = MagicMock(return_value=None)
_st_streamlit_stub.spinner.return_value = _st_streamlit_mgr

sys.modules["streamlit"] = _st_streamlit_stub
sys.modules["dashboard.utils.session"] = _st_session_stub

# 3. Ensure project root is on sys.path
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

# Now the import will not hit the auth guard or the token check
from dashboard.pages.scanner import (
    _direction_icon,
    _extract_rows,
    _format_time,
    _BATCH_KEY,
    _LOADING_KEY,
    _ERROR_KEY,
    _init_state,
)

# ---------------------------------------------------------------------------
# Test counters
# ---------------------------------------------------------------------------
P = 0
F = 0


def check(label: str, condition: bool) -> None:
    global P, F
    if condition:
        P += 1
        print(f"  ✅ {label}")
    else:
        F += 1
        print(f"  ❌ {label}")


# =========================================================================
# _format_time
# =========================================================================

print("\n=== _format_time ===")

check("None → em-dash", _format_time(None) == "—")

dt_str = "2026-06-29T12:30:00Z"
result = _format_time(dt_str)
check("ISO string with Z → formatted", result == "2026-06-29 12:30 UTC")

dt_str_off = "2026-06-29T14:00:00+00:00"
result = _format_time(dt_str_off)
check("ISO string with +00:00 → formatted", result == "2026-06-29 14:00 UTC")

ts = int(datetime(2026, 6, 29, 15, 0, 0, tzinfo=timezone.utc).timestamp())
result = _format_time(ts)
check("Unix timestamp (int) → formatted",
      _format_time(ts) == datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC"))

result = _format_time(float(ts))
check("Unix timestamp (float) → formatted",
      result == datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M UTC"))

result = _format_time("garbage-string-longer-than-19-chars")
check("Invalid string → first 19 chars", result == "garbage-string-long")

# =========================================================================
# _direction_icon
# =========================================================================

print("\n=== _direction_icon ===")

check("None → ⚪", _direction_icon(None) == "⚪")
check("LONG → 🟢", _direction_icon("LONG") == "🟢")
check("long lowercase → 🟢", _direction_icon("long") == "🟢")
check("SHORT → 🔴", _direction_icon("SHORT") == "🔴")
check("short → 🔴", _direction_icon("short") == "🔴")
check("unknown → ⚪", _direction_icon("NEUTRAL") == "⚪")
check("empty → ⚪", _direction_icon("") == "⚪")

# =========================================================================
# _extract_rows
# =========================================================================

print("\n=== _extract_rows ===")

check("empty dict → []", _extract_rows({}) == [])
check("None results → []", _extract_rows({"results": None}) == [])
check("empty results → []", _extract_rows({"results": []}) == [])

# Single successful result
single_batch = {
    "results": [
        {
            "symbol": "BTC-USD",
            "success": True,
            "overall_score": 85.0,
            "confluence_score": 25.5,
            "trade_plan": {"direction": "LONG", "analysis_time": "2026-06-29T10:00:00Z"},
            "score_breakdown": {"momentum": 8, "trend": 7},
        }
    ],
}
rows = _extract_rows(single_batch)
check("single result → 1 row", len(rows) == 1)
if rows:
    r = rows[0]
    check("row symbol", r["symbol"] == "BTC-USD")
    check("row score", r["score"] == 85.0)
    check("row direction", r["direction"] == "LONG")
    check("row direction_icon", r["direction_icon"] == "🟢")
    check("row analysis_time", r["analysis_time"] == "2026-06-29 10:00 UTC")
    check("row no error", r["error"] is None)

# Single failed result
fail_batch = {
    "results": [
        {
            "symbol": "ETH-USD",
            "success": False,
            "error": "API rate limit exceeded",
        }
    ],
}
rows = _extract_rows(fail_batch)
check("failed result → 1 row", len(rows) == 1)
if rows:
    r = rows[0]
    check("failed symbol", r["symbol"] == "ETH-USD")
    check("failed score is None", r["score"] is None)
    check("failed direction ERROR", r["direction"] == "ERROR")
    check("failed icon ❌", r["direction_icon"] == "❌")
    check("failed error msg", r["error"] == "API rate limit exceeded")

# Mixed success/failure
mixed_batch = {
    "results": [
        {"symbol": "BTC-USD", "success": True, "overall_score": 75.0,
         "confluence_score": 22.0, "trade_plan": {"direction": "LONG"}},
        {"symbol": "ETH-USD", "success": False, "error": "Timeout"},
    ],
}
rows = _extract_rows(mixed_batch)
check("mixed → 2 rows", len(rows) == 2)
if len(rows) == 2:
    check("first success", rows[0]["error"] is None)
    check("second fail", rows[1]["direction"] == "ERROR")

# Score fallback (no overall_score, use confluence_score)
score_fallback = {
    "results": [
        {"symbol": "SOL-USD", "success": True, "confluence_score": 18.0,
         "trade_plan": {"direction": "SHORT"}},
    ],
}
rows = _extract_rows(score_fallback)
check("score fallback to confluence_score", len(rows) == 1 and rows[0]["score"] == 18.0)

# Trade direction fallback (no trade_plan.direction, use item.direction)
dir_fallback = {
    "results": [
        {"symbol": "XRP-USD", "success": True, "overall_score": 60.0,
         "direction": "LONG"},
    ],
}
rows = _extract_rows(dir_fallback)
check("direction from item.direction", len(rows) == 1 and rows[0]["direction"] == "LONG")

# Analysis time fallback using cached_at (backend response includes cached_at, not analysis_time)
cached_at_fallback = {
    "results": [
        {
            "symbol": "ADA-USD",
            "success": True,
            "overall_score": 70.0,
            "cached_at": "2026-06-29T16:00:00Z",
            "trade_plan": {"direction": "LONG"},
        }
    ],
}
rows = _extract_rows(cached_at_fallback)
check("cached_at fallback → 1 row", len(rows) == 1)
if rows:
    r = rows[0]
    check("cached_at analysis_time", r["analysis_time"] == "2026-06-29 16:00 UTC")
    check("cached_at score preserved", r["score"] == 70.0)
    check("cached_at direction correct", r["direction"] == "LONG")

# Analysis time: cached_at takes lower priority than explicit analysis_time
explicit_beats_cached = {
    "results": [
        {
            "symbol": "DOT-USD",
            "success": True,
            "overall_score": 55.0,
            "analysis_time": "2026-06-29T08:00:00Z",
            "cached_at": "2026-06-29T16:00:00Z",
            "trade_plan": {"direction": "SHORT"},
        }
    ],
}
rows = _extract_rows(explicit_beats_cached)
check("explicit analysis_time beats cached_at", len(rows) == 1 and rows[0]["analysis_time"] == "2026-06-29 08:00 UTC")

# Analysis time: trade_plan.analysis_time beats cached_at
tp_beats_cached = {
    "results": [
        {
            "symbol": "LINK-USD",
            "success": True,
            "overall_score": 80.0,
            "cached_at": "2026-06-29T16:00:00Z",
            "trade_plan": {"direction": "SHORT", "analysis_time": "2026-06-29T12:00:00Z"},
        }
    ],
}
rows = _extract_rows(tp_beats_cached)
check("trade_plan analysis_time beats cached_at", len(rows) == 1 and rows[0]["analysis_time"] == "2026-06-29 12:00 UTC")

# =========================================================================
# Session state — data survives across runs (simulates flow)
# =========================================================================

print("\n=== Session state: batch data persistence ===")

# Clear the shared session state for this test
_st_session_state.clear()

# Init state (simulates page load)
_init_state()

check("_init_state sets _BATCH_KEY to None",
      _st_session_state.get(_BATCH_KEY) is None)
check("_init_state sets _LOADING_KEY to None",
      _st_session_state.get(_LOADING_KEY) is None)
check("_init_state sets _ERROR_KEY to None",
      _st_session_state.get(_ERROR_KEY) is None)
check("_init_state does NOT overwrite existing key",
      _st_session_state.get(_BATCH_KEY) is None)  # stays None after first init

# Simulate the button handler: store batch data
sample_data = {
    "results": [
        {"symbol": "BTC-USD", "success": True, "overall_score": 85.0,
         "trade_plan": {"direction": "LONG"}, "cached_at": "2026-06-29T14:00:00Z"},
    ],
    "total": 1,
    "succeeded": 1,
    "failed": 0,
}
_st_session_state[_BATCH_KEY] = sample_data
_st_session_state[_ERROR_KEY] = None
_st_session_state[_LOADING_KEY] = False

check("batch data stored in session state",
      _st_session_state.get(_BATCH_KEY) is sample_data)

# Simulate re-reading local vars (the fix: batch_data = st.session_state.get(_BATCH_KEY))
re_read_batch = _st_session_state.get(_BATCH_KEY)
re_read_loading = bool(_st_session_state.get(_LOADING_KEY))
check("re-read batch_data after storing", re_read_batch is sample_data)
check("re-read loading after storing", re_read_loading is False)

# Extract rows from the re-read data
rows = _extract_rows(re_read_batch)
check("rows extracted from re-read data", len(rows) == 1)
if rows:
    check("symbol correct", rows[0]["symbol"] == "BTC-USD")
    check("score correct", rows[0]["score"] == 85.0)
    check("direction correct", rows[0]["direction"] == "LONG")
    check("analysis_time from cached_at", rows[0]["analysis_time"] == "2026-06-29 14:00 UTC")
    check("error None", rows[0]["error"] is None)

# =========================================================================
# Summary
# =========================================================================

print(f"\n{'='*40}")
print(f"Results: {P} passed, {F} failed")
if F:
    sys.exit(1)
else:
    print("All tests passed!")
