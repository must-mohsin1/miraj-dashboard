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


def _request(
    method: str, path: str, token: Optional[str] = None,
    json: Any = None, params: Any = None, timeout: int = 15,
) -> dict:
    """Low-level request wrapper shared by all endpoint helpers."""
    try:
        resp = requests.request(
            method,
            f"{BASE_URL}{path}",
            headers=_headers(token),
            json=json,
            params=params,
            timeout=timeout,
        )
        return {"_resp": resp}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to backend server"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

def login(email: str, password: str) -> dict:
    """
    POST /api/v1/auth/login

    Returns ``{"success": True, "token": "..."}`` on success, or
    ``{"success": False, "error": "..."}`` on failure.
    """
    r = _request("POST", "/api/v1/auth/login", json={"username": email, "password": password})
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 200:
        data = _safe_json(resp)
        return {"success": True, "token": data["access_token"]}
    detail = _safe_json(resp).get("detail", "Login failed")
    return {"success": False, "error": str(detail)}


def register(email: str, password: str) -> dict:
    """
    POST /api/v1/auth/register

    Returns ``{"success": True}`` on success, or
    ``{"success": False, "error": "..."}`` on failure.
    """
    r = _request("POST", "/api/v1/auth/register", json={"username": email, "email": email, "password": password})
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code in (200, 201):
        return {"success": True}
    detail = _safe_json(resp).get("detail", "Registration failed")
    return {"success": False, "error": str(detail)}


# ---------------------------------------------------------------------------
# Macro data
# ---------------------------------------------------------------------------

def get_macro(token: str) -> dict:
    """
    GET /api/v1/macro

    Returns ``{"success": True, "data": {...}}`` or
    ``{"success": False, "error": "..."}``.
    """
    r = _request("GET", "/api/v1/macro", token=token)
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 200:
        return {"success": True, "data": _safe_json(resp)}
    detail = _safe_json(resp).get("detail", "Failed to fetch macro data")
    return {"success": False, "error": str(detail)}


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
    r = _request("POST", f"/api/v1/scan/{symbol}", token=token, timeout=120)
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code in (200, 201):
        return {"success": True, "data": _safe_json(resp)}
    detail = _safe_json(resp).get("detail", "Scan failed")
    return {"success": False, "error": str(detail)}


def get_analysis(symbol: str, token: str) -> dict:
    """
    GET /api/v1/scan/{symbol}

    Fetch an existing (possibly cached) analysis result.
    Returns ``{"success": True, "data": {...}}`` or
    ``{"success": False, "error": "..."}``.
    """
    r = _request("GET", f"/api/v1/scan/{symbol}", token=token)
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 200:
        return {"success": True, "data": _safe_json(resp)}
    if resp.status_code == 404:
        return {"success": False, "error": "No analysis found for this symbol"}
    detail = _safe_json(resp).get("detail", "Failed to fetch analysis")
    return {"success": False, "error": str(detail)}


def scan_batch(token: str) -> dict:
    """
    POST /api/v1/scan/batch

    Triggers a batch scan for all pairs in the user's watchlist.
    Returns ``{"success": True, "data": [scan_result, ...]}`` or
    ``{"success": False, "error": "..."}``.
    """
    r = _request("POST", "/api/v1/scan/batch", token=token, timeout=300)
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code in (200, 201):
        return {"success": True, "data": _safe_json(resp)}
    detail = _safe_json(resp).get("detail", "Batch scan failed")
    return {"success": False, "error": str(detail)}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def get_history(
    token: str,
    page: int = 1,
    per_page: int = 20,
    symbol: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    min_score: Optional[float] = None,
) -> dict:
    """
    GET /api/v1/history

    Paginated list of past analyses with optional filters.
    Returns ``{"success": True, "data": {...}}`` on success.
    """
    params: dict[str, Any] = {"page": page, "per_page": per_page}
    if symbol:
        params["symbol"] = symbol
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    if min_score is not None:
        params["min_score"] = min_score

    r = _request("GET", "/api/v1/history", token=token, params=params)
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 200:
        return {"success": True, "data": _safe_json(resp)}
    detail = _safe_json(resp).get("detail", "Failed to fetch history")
    return {"success": False, "error": str(detail)}


def delete_analysis(analysis_id: int, token: str) -> dict:
    """
    DELETE /api/v1/history/{analysis_id}

    Delete a single analysis row.
    Returns ``{"success": True, "data": {...}}`` on success.
    """
    r = _request("DELETE", f"/api/v1/history/{analysis_id}", token=token)
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 200:
        return {"success": True, "data": _safe_json(resp)}
    if resp.status_code == 404:
        return {"success": False, "error": "Analysis not found"}
    detail = _safe_json(resp).get("detail", "Failed to delete analysis")
    return {"success": False, "error": str(detail)}


def export_history(ids: list[int], token: str) -> dict:
    """
    GET /api/v1/history/export?ids=1,2,3

    Download a markdown report for the selected analysis ids.
    Returns ``{"success": True, "data": "...markdown..."}`` on success.
    """
    ids_str = ",".join(str(i) for i in ids)
    r = _request("GET", "/api/v1/history/export", token=token, params={"ids": ids_str})
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 200:
        return {"success": True, "data": resp.text}
    detail = resp.text or "Export failed"
    return {"success": False, "error": str(detail)}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def get_watchlist(token: str) -> dict:
    """
    GET /api/v1/watchlist

    Returns ``{"success": True, "data": {"pairs": [...], "total": N}}`` on
    success, or ``{"success": False, "error": "..."}`` on failure.
    """
    r = _request("GET", "/api/v1/watchlist", token=token)
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 200:
        return {"success": True, "data": _safe_json(resp)}
    detail = _safe_json(resp).get("detail", "Failed to fetch watchlist")
    return {"success": False, "error": str(detail)}


def add_watchlist_pair(pair: str, token: str) -> dict:
    """
    POST /api/v1/watchlist

    Add a pair to the user's watchlist.
    Returns ``{"success": True, "data": {...}}`` on success, or
    ``{"success": False, "error": "..."}`` on failure.
    """
    r = _request("POST", "/api/v1/watchlist", token=token, json={"pair": pair})
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code in (200, 201):
        return {"success": True, "data": _safe_json(resp)}
    if resp.status_code == 409:
        detail = _safe_json(resp).get("detail", "Pair already in watchlist")
        return {"success": False, "error": str(detail)}
    detail = _safe_json(resp).get("detail", "Failed to add pair")
    return {"success": False, "error": str(detail)}


def remove_watchlist_pair(pair_id: int, token: str) -> dict:
    """
    DELETE /api/v1/watchlist/{pair_id}

    Remove a pair from the user's watchlist by database id.
    Returns ``{"success": True}`` on success, or
    ``{"success": False, "error": "..."}`` on failure.
    """
    r = _request("DELETE", f"/api/v1/watchlist/{pair_id}", token=token)
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 204:
        return {"success": True}
    if resp.status_code == 404:
        return {"success": False, "error": "Pair not found in watchlist"}
    detail = _safe_json(resp).get("detail", "Failed to remove pair")
    return {"success": False, "error": str(detail)}


def reorder_watchlist(pair_ids: list[int], token: str) -> dict:
    """
    PUT /api/v1/watchlist/reorder

    Reorder watchlist pairs. ``pair_ids`` is the desired display order of pair database IDs.
    Returns ``{"success": True, "data": {...}}`` on success, or
    ``{"success": False, "error": "..."}`` on failure.
    """
    r = _request("PUT", "/api/v1/watchlist/reorder", token=token, json={"pair_ids": pair_ids})
    if "_resp" not in r:
        return r
    resp = r["_resp"]
    if resp.status_code == 200:
        return {"success": True, "data": _safe_json(resp)}
    detail = _safe_json(resp).get("detail", "Failed to reorder")
    return {"success": False, "error": str(detail)}
