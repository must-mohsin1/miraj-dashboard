"""Tests for backend/services/macro_service.py — DXY + FRED API integration.

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production \\
      python -m pytest backend/tests/test_macro_service.py -v

"""

from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import-time)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.services.macro_service import (
    _cache,
    _fetch_dxy,
    build_response,
    refresh_macro_data,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear the in-memory cache before each test."""
    for key in _cache:
        _cache[key]["value"] = None
        _cache[key]["error"] = None
    yield


# ---------------------------------------------------------------------------
# _fetch_dxy — no API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_dxy_no_api_key():
    """When FRED_API_KEY is not set, return None with a clear message."""
    # Ensure the env var is absent
    old = os.environ.pop("FRED_API_KEY", None)
    try:
        val, err = await _fetch_dxy()
        assert val is None
        assert err == "Set FRED_API_KEY for DXY data"
    finally:
        if old is not None:
            os.environ["FRED_API_KEY"] = old


# ---------------------------------------------------------------------------
# _fetch_dxy — API key set, FRED returns valid data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_dxy_with_key_success():
    """When FRED_API_KEY is set and FRED returns valid data, return the float."""
    mock_observations = {
        "observations": [{"value": "104.25"}],
    }

    with patch(
        "backend.services.macro_service._fetch_json",
        new_callable=AsyncMock,
        return_value=mock_observations,
    ), patch.dict(os.environ, {"FRED_API_KEY": "test-key-123"}):
        val, err = await _fetch_dxy()
        assert val == 104.25
        assert err is None


# ---------------------------------------------------------------------------
# _fetch_dxy — API key set, FRED returns placeholder "." (not yet available)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_dxy_value_not_yet_available():
    """When FRED returns a '.' value, indicate it's not yet available."""
    mock_observations = {
        "observations": [{"value": "."}],
    }

    with patch(
        "backend.services.macro_service._fetch_json",
        new_callable=AsyncMock,
        return_value=mock_observations,
    ), patch.dict(os.environ, {"FRED_API_KEY": "test-key-123"}):
        val, err = await _fetch_dxy()
        assert val is None
        assert err == "DXY value is '.' (not yet available)"


# ---------------------------------------------------------------------------
# _fetch_dxy — API key set, FRED fetch fails (returns None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_dxy_key_set_but_api_fails():
    """When FRED_API_KEY is set but the FRED request fails, give a distinct
    error message (not 'not configured')."""
    with patch(
        "backend.services.macro_service._fetch_json",
        new_callable=AsyncMock,
        return_value=None,
    ), patch.dict(os.environ, {"FRED_API_KEY": "test-key-123"}):
        val, err = await _fetch_dxy()
        assert val is None
        assert err == "FRED API error — could not fetch DXY data"


# ---------------------------------------------------------------------------
# build_response — dxy_error included when DXY is None
# ---------------------------------------------------------------------------


def test_build_response_includes_dxy_error():
    """When DXY value is None and an error exists, ``dxy_error`` should be
    present in the data dict."""
    _cache["dxy"]["value"] = None
    _cache["dxy"]["error"] = "Set FRED_API_KEY for DXY data"

    resp = build_response()
    data = resp["data"]
    assert data["dxy"] is None
    assert data["dxy_error"] == "Set FRED_API_KEY for DXY data"


def test_build_response_no_dxy_error_when_value_present():
    """When DXY has a value, ``dxy_error`` should be None."""
    _cache["dxy"]["value"] = 104.25
    _cache["dxy"]["error"] = None

    resp = build_response()
    data = resp["data"]
    assert data["dxy"] == 104.25
    assert data["dxy_error"] is None


def test_build_response_dxy_error_is_none_when_no_error():
    """When DXY value is None but no error is recorded, ``dxy_error`` is
    None (matches fallback '—' behaviour)."""
    _cache["dxy"]["value"] = None
    _cache["dxy"]["error"] = None

    resp = build_response()
    data = resp["data"]
    assert data["dxy"] is None
    assert data["dxy_error"] is None


# ---------------------------------------------------------------------------
# refresh_macro_data — smoke test that dxy_error flows through from cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_macro_data_dxy_error_smoke():
    """After a macro refresh, dxy_error should be set if DXY fetch fails."""
    # Mock every slow HTTP call to return None (all fetches fail)
    async def _mock_none(*args: Any, **kwargs: Any) -> None:
        return None

    with patch(
        "backend.services.macro_service._fetch_json",
        new_callable=AsyncMock,
        side_effect=_mock_none,
    ), patch.dict(os.environ, clear=True):
        resp = await refresh_macro_data()

    data = resp["data"]
    assert "dxy_error" in data
    assert data["dxy"] is None
    # When no FRED_API_KEY is set, the error should be the no-key message
    assert data["dxy_error"] == "Set FRED_API_KEY for DXY data"
