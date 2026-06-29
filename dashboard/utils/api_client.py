"""
HTTP client helpers for the crypto analysis backend.

All functions return a standard dict with ``{"success": bool, ...}`` so
callers can handle errors uniformly without try/except blocks.
"""

from __future__ import annotations

from typing import Any, Optional

import requests

# ---------------------------------------------------------------------------
# Base URL  (default: localhost; override via set_base_url for Docker, etc.)
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:8000"


def set_base_url(url: str) -> None:
    """Override the backend base URL (strip trailing slash)."""
    global BASE_URL
    BASE_URL = url.rstrip("/")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _headers(token: Optional[str] = None) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _safe_json(resp: requests.Response) -> Any:
    """Return parsed JSON or a fallback error dict."""
    try:
        return resp.json()
    except ValueError:
        return {"detail": resp.text or "Unknown error"}


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

def login(email: str, password: str) -> dict:
    """
    POST /api/v1/auth/login

    Returns ``{"success": True, "token": "..."}`` on success, or
    ``{"success": False, "error": "..."}`` on failure.
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": email, "password": password},
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            data = _safe_json(resp)
            return {"success": True, "token": data["access_token"]}
        detail = _safe_json(resp).get("detail", "Login failed")
        return {"success": False, "error": str(detail)}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to backend server"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def register(email: str, password: str) -> dict:
    """
    POST /api/v1/auth/register

    Returns ``{"success": True}`` on success, or
    ``{"success": False, "error": "..."}`` on failure.
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/auth/register",
            json={"username": email, "email": email, "password": password},
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return {"success": True}
        detail = _safe_json(resp).get("detail", "Registration failed")
        return {"success": False, "error": str(detail)}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to backend server"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Macro data
# ---------------------------------------------------------------------------

def get_macro(token: str) -> dict:
    """
    GET /api/v1/macro

    Returns ``{"success": True, "data": {...}}`` or
    ``{"success": False, "error": "..."}``.
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v1/macro",
            headers=_headers(token),
            timeout=15,
        )
        if resp.status_code == 200:
            return {"success": True, "data": _safe_json(resp)}
        detail = _safe_json(resp).get("detail", "Failed to fetch macro data")
        return {"success": False, "error": str(detail)}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to backend server"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Scan / analysis
# ---------------------------------------------------------------------------

def scan_symbol(symbol: str, token: str) -> dict:
    """
    POST /api/v1/scan/{symbol}

    Triggers a new analysis pipeline for the given trading pair.
    Returns ``{"success": True, "data": {...}}`` or
    ``{"success": False, "error": "..."}``.
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/scan/{symbol}",
            headers=_headers(token),
            timeout=120,  # pipeline can take up to 60 s
        )
        if resp.status_code in (200, 201):
            return {"success": True, "data": _safe_json(resp)}
        detail = _safe_json(resp).get("detail", "Scan failed")
        return {"success": False, "error": str(detail)}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to backend server"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def get_analysis(symbol: str, token: str) -> dict:
    """
    GET /api/v1/scan/{symbol}

    Fetch an existing (possibly cached) analysis result.
    Returns ``{"success": True, "data": {...}}`` or
    ``{"success": False, "error": "..."}``.
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v1/scan/{symbol}",
            headers=_headers(token),
            timeout=15,
        )
        if resp.status_code == 200:
            return {"success": True, "data": _safe_json(resp)}
        if resp.status_code == 404:
            return {"success": False, "error": "No analysis found for this symbol"}
        detail = _safe_json(resp).get("detail", "Failed to fetch analysis")
        return {"success": False, "error": str(detail)}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to backend server"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
