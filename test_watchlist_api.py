"""Tests for watchlist CRUD + batch scan endpoint (P2-A).

Run with::

    cd /Users/mustcompanymohsin/projects/miraj-dashboard
    JWT_SECRET_KEY=test-secret .venv/bin/python -m pytest test_watchlist_api.py -v --tb=short -q
"""

from __future__ import annotations

import os
import sys

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORKSPACE)

os.environ["JWT_SECRET_KEY"] = "test-secret-watchlist-p2-a"

import pytest
from fastapi.testclient import TestClient

from backend.database import set_db_path
from backend.main import app
from backend.models import WatchlistPair
from backend.services.analysis_service import clear_cache
from backend.services.batch_scanner import (
    can_run_batch,
    clear_rate_limit,
    mark_batch_run,
    seconds_until_retry,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared TestClient fixture — one per test session (module)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def module_client():
    """Create a single TestClient used by all tests in this module.

    The lifespan runs once (creating tables) and stays alive for the
    duration of the module, avoiding event-loop conflicts.
    """
    db_path = os.path.join(WORKSPACE, "test_watchlist.db")
    # Clean up from prior runs
    for f in os.listdir(WORKSPACE):
        if f.startswith("test_watchlist") and f.endswith(".db"):
            os.remove(os.path.join(WORKSPACE, f))
    set_db_path(db_path)

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def _mock_batch_scan():
    """Module-scoped mock for run_batch_scan to keep batch scan tests fast."""
    import unittest.mock as mock
    patcher = mock.patch(
        "backend.routes.watchlist.run_batch_scan",
        return_value=[
            {"symbol": "BTCUSDT", "confluence_score": 15.5,
             "trade_plan": {"trade_decision": True, "direction": "LONG"},
             "score_breakdown": {"total": 15.5}, "stale": False, "cached_at": None},
            {"symbol": "ETHUSDT", "confluence_score": 12.0,
             "trade_plan": {"trade_decision": True, "direction": "LONG"},
             "score_breakdown": {"total": 12.0}, "stale": False, "cached_at": None},
        ],
    )
    patcher.start()
    yield
    patcher.stop()


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean caches and rate limits before each test."""
    clear_cache()
    clear_rate_limit()
    yield


@pytest.fixture
def user_token(module_client) -> str:
    """Register + login a unique user, return auth token."""
    import time
    ts = int(time.time() * 1000)
    username = f"u_{ts}"
    email = f"{username}@test.com"

    r = module_client.post("/api/v1/auth/register", json={
        "username": username,
        "email": email,
        "password": "testpass123",
    })
    assert r.status_code == 201, f"Register: {r.text}"

    r = module_client.post("/api/v1/auth/login", json={
        "username": username,
        "password": "testpass123",
    })
    assert r.status_code == 200, f"Login: {r.text}"
    return r.json()["access_token"]


@pytest.fixture
def auth_h(user_token) -> dict:
    return {"Authorization": f"Bearer {user_token}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Watchlist CRUD tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_crud_flow(module_client, auth_h):
    """Full CRUD flow: add -> list -> duplicate -> reorder -> delete.

    Uses the current API contract (P2-D):
    - reorder body expects ``pair_ids`` (list of int)
    - reorder response returns ``reordered`` (int)
    - delete expects int path param
    - GET returns ``WatchlistListResponse`` shape: {total, pairs}
    """
    c = module_client

    # ---- Add pair ----
    resp = c.post("/api/v1/watchlist", json={"pair": "BTCUSDT"}, headers=auth_h)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["pair"] == "BTCUSDT"
    assert data["sort_order"] == 0
    btc_id = data["id"]

    # ---- Add second pair ----
    resp = c.post("/api/v1/watchlist", json={"pair": "ETHUSDT"}, headers=auth_h)
    assert resp.status_code == 201, resp.text
    assert resp.json()["pair"] == "ETHUSDT"
    assert resp.json()["sort_order"] == 1
    eth_id = resp.json()["id"]

    # ---- List pairs ----
    resp = c.get("/api/v1/watchlist", headers=auth_h)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    pairs = data["pairs"]
    assert pairs[0]["pair"] == "BTCUSDT"
    assert pairs[1]["pair"] == "ETHUSDT"

    # ---- Duplicate -> 409 ----
    resp = c.post("/api/v1/watchlist", json={"pair": "BTCUSDT"}, headers=auth_h)
    assert resp.status_code == 409, resp.text
    assert "already" in resp.json()["detail"].lower()

    # ---- Reorder (swap order by pair_ids) ----
    resp = c.put(
        "/api/v1/watchlist/reorder",
        json={"pair_ids": [eth_id, btc_id]},
        headers=auth_h,
    )
    assert resp.status_code == 200
    assert resp.json()["reordered"] == 2

    # ---- Verify reorder ----
    resp = c.get("/api/v1/watchlist", headers=auth_h)
    pairs = resp.json()["pairs"]
    assert pairs[0]["pair"] == "ETHUSDT"
    assert pairs[1]["pair"] == "BTCUSDT"

    # ---- Delete by int ID ----
    resp = c.delete(f"/api/v1/watchlist/{btc_id}", headers=auth_h)
    assert resp.status_code == 204

    resp = c.get("/api/v1/watchlist", headers=auth_h)
    data = resp.json()
    assert data["total"] == 1
    assert data["pairs"][0]["pair"] == "ETHUSDT"

    # ---- Delete non-existent returns 404 ----
    resp = c.delete("/api/v1/watchlist/99999", headers=auth_h)
    assert resp.status_code == 404

    # ---- Delete last ----
    resp = c.delete(f"/api/v1/watchlist/{eth_id}", headers=auth_h)
    assert resp.status_code == 204

    # ---- Empty list returns WatchlistListResponse shape ----
    resp = c.get("/api/v1/watchlist", headers=auth_h)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["pairs"] == []


def test_batch_scan_no_auth(module_client):
    """POST /api/v1/scan/batch without auth returns 401."""
    resp = module_client.post("/api/v1/scan/batch")
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Batch scan tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_batch_scan_empty_watchlist(module_client, auth_h):
    """Batch scan with empty watchlist returns empty wrapper dict."""
    clear_rate_limit()
    resp = module_client.post("/api/v1/scan/batch", headers=auth_h)
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"results": [], "total": 0, "succeeded": 0, "failed": 0}


def test_batch_scan_rate_limit(module_client, auth_h, _mock_batch_scan):
    """Rate limiting blocks a second batch scan within 5 minutes."""
    clear_rate_limit()
    c = module_client

    # Add a pair so batch scan has something to process
    c.post("/api/v1/watchlist", json={"pair": "BTCUSDT"}, headers=auth_h)

    # First batch scan — should succeed
    resp1 = c.post("/api/v1/scan/batch", headers=auth_h)
    assert resp1.status_code == 200, (
        f"Expected 200, got {resp1.status_code}: {resp1.text[:200]}"
    )

    # Second immediate call — should be rate-limited
    resp2 = c.post("/api/v1/scan/batch", headers=auth_h)
    assert resp2.status_code == 429, (
        f"Expected 429, got {resp2.status_code}: {resp2.text[:200]}"
    )
    assert "Retry-After" in resp2.headers
    assert int(resp2.headers["Retry-After"]) > 0


def test_batch_scan_returns_sorted_results(module_client, auth_h, _mock_batch_scan):
    """Batch scan returns results wrapped in {results, total, succeeded, failed}."""
    clear_rate_limit()
    c = module_client

    # Add two pairs
    c.post("/api/v1/watchlist", json={"pair": "BTCUSDT"}, headers=auth_h)
    c.post("/api/v1/watchlist", json={"pair": "ETHUSDT"}, headers=auth_h)

    resp = c.post("/api/v1/scan/batch", headers=auth_h)
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "total" in data
    assert "succeeded" in data
    assert "failed" in data
    results = data["results"]
    assert len(results) == 2
    assert results[0]["symbol"] == "BTCUSDT"
    assert results[1]["symbol"] == "ETHUSDT"
    assert results[0]["confluence_score"] >= results[1]["confluence_score"]
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests for batch scanner service (no DB / app needed)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBatchScannerService:

    def setup_method(self):
        clear_rate_limit()

    def test_can_run_batch_first_time(self):
        assert can_run_batch(42) is True

    def test_can_run_batch_cooldown(self):
        mark_batch_run(42)
        assert can_run_batch(42) is False
        assert seconds_until_retry(42) > 0

    def test_can_run_batch_after_clear(self):
        mark_batch_run(42)
        assert can_run_batch(42) is False
        clear_rate_limit(42)
        assert can_run_batch(42) is True

    def test_clear_rate_limit_all(self):
        mark_batch_run(1)
        mark_batch_run(2)
        assert can_run_batch(1) is False
        clear_rate_limit()
        assert can_run_batch(1) is True
        assert can_run_batch(2) is True

    def test_seconds_until_retry_zero_when_no_record(self):
        assert seconds_until_retry(99) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Model tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_watchlist_pair_unique_constraint():
    table = WatchlistPair.__table__
    names = [c.name for c in table.constraints if hasattr(c, "name")]
    assert "uq_user_pair" in names


def test_watchlist_pair_has_sort_order():
    cols = [c.name for c in WatchlistPair.__table__.columns]
    assert "sort_order" in cols
