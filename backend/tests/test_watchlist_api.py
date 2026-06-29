"""Tests for the Watchlist API (P2-D).

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_watchlist_api.py -v

Tests use an isolated temporary SQLite database file (not :memory:) so that
the auth dependency (which opens its own session) and the route's DB session
both see the same data.
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import Any, AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import time)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.auth import create_access_token, hash_password
from backend.database import Base, get_session, set_db_path
from backend.models import User


# ── Internal helpers ─────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    """Return a fresh FastAPI app with all routers."""
    from backend.main import app

    return app


async def _create_user(session, username: str = "testuser", email: str = "test@example.com") -> User:
    """Create and return a test user."""
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _token_for(user_id: int) -> str:
    """Create a valid JWT for the given user id."""
    return create_access_token(data={"sub": str(user_id)})


# ── Pytest fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    """Yield a unique temporary DB path per test, cleaned up after."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="wl_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def app(tmp_db_path: str) -> FastAPI:
    """Return a fully-initialized FastAPI app pointed at *tmp_db_path*.

    We force the database path before any engine/session is created by
    importing the app module lazily *after* setting the path.
    """
    from backend import database

    # Reset singletons
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None

    set_db_path(tmp_db_path)

    app = _make_app()

    # Create tables
    from backend.database import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Yield an async HTTP client for the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Tests ────────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.anyio


class TestWatchlistAPI:
    """Integration tests for watchlist CRUD + reorder endpoints."""

    @staticmethod
    async def _add_pair(client: AsyncClient, pair: str, token: str) -> dict:
        resp = await client.post(
            "/api/v1/watchlist",
            json={"pair": pair},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, f"Failed to add {pair}: {resp.text}"
        return resp.json()

    # ── Basic CRUD ──────────────────────────────────────────────────────

    async def test_empty_watchlist(self, app: FastAPI, client: AsyncClient):
        """GET /api/v1/watchlist returns empty list for a new user."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        resp = await client.get(
            "/api/v1/watchlist",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["pairs"] == []

    async def test_add_pair(self, app: FastAPI, client: AsyncClient):
        """POST /api/v1/watchlist adds a pair and returns its details."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        resp = await client.post(
            "/api/v1/watchlist",
            json={"pair": "BTC-USD"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["pair"] == "BTC-USD"
        assert data["user_id"] == user.id
        assert "id" in data
        assert "sort_order" in data

    async def test_add_duplicate_pair(self, app: FastAPI, client: AsyncClient):
        """POST with an existing pair returns 409."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        await self._add_pair(client, "ETH-USD", token)
        resp = await client.post(
            "/api/v1/watchlist",
            json={"pair": "ETH-USD"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409
        assert "already" in resp.json()["detail"].lower()

    async def test_remove_pair(self, app: FastAPI, client: AsyncClient):
        """DELETE /api/v1/watchlist/{id} removes the pair."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        pair = await self._add_pair(client, "LINK-USD", token)
        pair_id = pair["id"]

        del_resp = await client.delete(
            f"/api/v1/watchlist/{pair_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert del_resp.status_code == 204

        # Verify it's gone
        get_resp = await client.get(
            "/api/v1/watchlist",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.json()["total"] == 0

    async def test_remove_nonexistent_pair(self, app: FastAPI, client: AsyncClient):
        """DELETE for a non-existent pair returns 404."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        resp = await client.delete(
            "/api/v1/watchlist/99999",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    # ── Sorting & reorder ───────────────────────────────────────────────

    async def test_add_multiple_pairs_sorted(self, app: FastAPI, client: AsyncClient):
        """Pairs are returned in sort_order ascending."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        pairs_to_add = ["SOL-USD", "ADA-USD", "DOT-USD"]
        for p in pairs_to_add:
            await self._add_pair(client, p, token)

        resp = await client.get(
            "/api/v1/watchlist",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        returned_pairs = [p["pair"] for p in data["pairs"]]
        assert returned_pairs == pairs_to_add

    async def test_reorder_pairs(self, app: FastAPI, client: AsyncClient):
        """PUT /api/v1/watchlist/reorder changes sort_order."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        ids = []
        for p in ["XRP-USD", "AVAX-USD", "MATIC-USD"]:
            pair = await self._add_pair(client, p, token)
            ids.append(pair["id"])

        reversed_ids = list(reversed(ids))
        reorder_resp = await client.put(
            "/api/v1/watchlist/reorder",
            json={"pair_ids": reversed_ids},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reorder_resp.status_code == 200
        assert reorder_resp.json()["reordered"] == 3

        get_resp = await client.get(
            "/api/v1/watchlist",
            headers={"Authorization": f"Bearer {token}"},
        )
        new_ids = [p["id"] for p in get_resp.json()["pairs"]]
        assert new_ids == reversed_ids

    async def test_reorder_with_invalid_ids(self, app: FastAPI, client: AsyncClient):
        """PUT reorder with non-owned IDs returns 400."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        # Add one pair so we have something, then try to reorder with bad ids
        pair = await self._add_pair(client, "BTC-USD", token)

        resp = await client.put(
            "/api/v1/watchlist/reorder",
            json={"pair_ids": [999, 888]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        assert "Invalid" in resp.json()["detail"]

    # ── Normalization ───────────────────────────────────────────────────

    async def test_add_pair_normalization(self, app: FastAPI, client: AsyncClient):
        """Pair symbols are uppercased and stripped."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        resp = await client.post(
            "/api/v1/watchlist",
            json={"pair": "  btc-usd  "},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["pair"] == "BTC-USD"

    # ── Auth / isolation ────────────────────────────────────────────────

    async def test_requires_auth(self, client: AsyncClient):
        """All watchlist endpoints return 401 without a valid token."""
        for method, path in [
            ("GET", "/api/v1/watchlist"),
            ("POST", "/api/v1/watchlist"),
            ("DELETE", "/api/v1/watchlist/1"),
            ("PUT", "/api/v1/watchlist/reorder"),
        ]:
            resp = await client.request(method, path)
            assert resp.status_code == 401, f"{method} {path} did not return 401"

    async def test_user_isolation(self, app: FastAPI, client: AsyncClient):
        """User A's pairs should not be visible to User B."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user_a = await _create_user(session, username="user_a", email="a@test.com")
            user_b = await _create_user(session, username="user_b", email="b@test.com")
            await session.commit()
            token_a = _token_for(user_a.id)
            token_b = _token_for(user_b.id)

        # User A adds a pair
        await self._add_pair(client, "BTC-USD", token_a)

        # User B should see an empty list
        resp = await client.get(
            "/api/v1/watchlist",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.json()["total"] == 0

    # ── Response shape ──────────────────────────────────────────────────

    async def test_score_in_response(self, app: FastAPI, client: AsyncClient):
        """Watchlist response includes score and status fields."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)

        await self._add_pair(client, "BTC-USD", token)

        resp = await client.get(
            "/api/v1/watchlist",
            headers={"Authorization": f"Bearer {token}"},
        )
        pair = resp.json()["pairs"][0]
        assert "score" in pair
        assert "status" in pair
        assert pair["status"] == "Active"
