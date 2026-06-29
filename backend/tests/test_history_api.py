"""Tests for the History API (P2-Fix-3: min_score pagination).

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_history_api.py -v

Tests use an isolated temporary SQLite database file so that
the auth dependency (which opens its own session) and the route's DB session
both see the same data.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from typing import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import time)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.auth import create_access_token, hash_password
from backend.database import Base, set_db_path
from backend.models import Analysis, User


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_result_blob(score: float | None) -> str:
    """Build a JSON result blob with the given overall_score."""
    return json.dumps({
        "overall_score": score,
        "confluence_score": score,
        "trade_plan": {
            "direction": "LONG" if score and score >= 50 else "SHORT",
            "trade_decision": score is not None and score >= 60,
        },
        "score_breakdown": {"trend": score, "momentum": score, "volume": score},
    })


async def _create_user(session, username: str = "historyuser", email: str = "history@example.com") -> User:
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
    fd, path = tempfile.mkstemp(suffix=".db", prefix="hist_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def app(tmp_db_path: str) -> FastAPI:
    """Return a fully-initialized FastAPI app pointed at *tmp_db_path*."""
    from backend import database

    # Reset singletons
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None

    set_db_path(tmp_db_path)

    from backend.main import app as _app

    # Create tables
    from backend.database import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return _app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Yield an async HTTP client for the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Test class ───────────────────────────────────────────────────────────────

pytestmark = pytest.mark.anyio


class TestHistoryAPI:
    """Integration tests for the history endpoint, focusing on filter pagination."""

    @staticmethod
    async def _get_user_and_token(app: FastAPI) -> tuple[User, str]:
        """Create a user, return (user, token)."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await _create_user(session)
            await session.commit()
            token = _token_for(user.id)
        return user, token

    @staticmethod
    async def _insert_analyses(app: FastAPI, user: User, scores: list[float | None], prefix: str = "PAIR") -> None:
        """Insert one Analysis row per score in *scores*."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            for i, score in enumerate(scores):
                session.add(Analysis(
                    user_id=user.id,
                    pair=f"{prefix}-{i}",
                    analysis_type="scan",
                    score=score,
                    result=_make_result_blob(score),
                    created_at=datetime.utcnow() - timedelta(hours=i),
                ))
            await session.commit()

    # ── Basic history tests ─────────────────────────────────────────────

    async def test_empty_history(self, app: FastAPI, client: AsyncClient):
        """GET /api/v1/history returns empty for a new user."""
        user, token = await self._get_user_and_token(app)

        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["rows"] == []
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert data["pages"] == 1

    async def test_requires_auth(self, client: AsyncClient):
        """History endpoints return 401 without a valid token."""
        resp = await client.get("/api/v1/history")
        assert resp.status_code == 401

    async def test_delete_requires_auth(self, client: AsyncClient):
        """DELETE history/{id} returns 401 without a valid token."""
        resp = await client.delete("/api/v1/history/1")
        assert resp.status_code == 401

    # ── Pagination correctness ─────────────────────────────────────────

    async def test_pagination_defaults(self, app: FastAPI, client: AsyncClient):
        """Default pagination returns page=1, per_page=20."""
        user, token = await self._get_user_and_token(app)
        await self._insert_analyses(app, user, [50.0 + i * 10 for i in range(5)])

        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert data["total"] == 5
        assert data["pages"] == 1
        assert len(data["rows"]) == 5

    async def test_pagination_multiple_pages(self, app: FastAPI, client: AsyncClient):
        """Pagination correctly returns page 2 with per_page=3."""
        user, token = await self._get_user_and_token(app)
        await self._insert_analyses(app, user, [50.0] * 10)

        # Page 1 of 4 (per_page=3, total=10 → pages=4)
        resp1 = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"page": 1, "per_page": 3},
        )
        d1 = resp1.json()
        assert d1["total"] == 10
        assert d1["pages"] == 4
        assert len(d1["rows"]) == 3

        # Page 2
        resp2 = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"page": 2, "per_page": 3},
        )
        d2 = resp2.json()
        assert d2["page"] == 2
        assert len(d2["rows"]) == 3

        # Verify no overlap
        ids1 = {r["id"] for r in d1["rows"]}
        ids2 = {r["id"] for r in d2["rows"]}
        assert ids1.isdisjoint(ids2), (
            f"Page 1 and Page 2 share rows: {ids1 & ids2}"
        )

    # ── min_score filter ───────────────────────────────────────────────

    async def test_min_score_filter_no_exclusions(self, app: FastAPI, client: AsyncClient):
        """min_score=0 excludes NULL but includes all numeric rows."""
        user, token = await self._get_user_and_token(app)
        await self._insert_analyses(app, user, [0, 10, 50, 90, None])

        # min_score=0 — excludes NULL, includes 0, 10, 50, 90
        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"min_score": 0},
        )
        data = resp.json()
        # SQL WHERE score >= 0 excludes NULL
        assert data["total"] == 4, f"Expected 4 rows (0, 10, 50, 90), got {data['total']}"

    async def test_min_score_filter_excludes_low(self, app: FastAPI, client: AsyncClient):
        """min_score=60 includes only rows with score >= 60."""
        user, token = await self._get_user_and_token(app)
        await self._insert_analyses(app, user, [0, 10, 30, 50, 60, 70, 90, 100])

        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"min_score": 60},
        )
        data = resp.json()
        assert data["total"] == 4, f"Expected 4 rows (60, 70, 90, 100), got {data['total']}"
        for row in data["rows"]:
            assert row["score"] is not None
            assert row["score"] >= 60, f"Row {row['id']} has score {row['score']} < 60"

    async def test_min_score_with_none_scores(self, app: FastAPI, client: AsyncClient):
        """NULL scores are excluded when min_score > 0."""
        user, token = await self._get_user_and_token(app)
        await self._insert_analyses(app, user, [None, 30, None, 70, None])

        # min_score=50 — should only include 70
        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"min_score": 50},
        )
        data = resp.json()
        assert data["total"] == 1, f"Expected 1 row (70), got {data['total']}"
        assert data["rows"][0]["score"] == 70

    # ── min_score + pagination interaction (the original bug) ─────────

    async def test_min_score_pagination_correct_total(self, app: FastAPI, client: AsyncClient):
        """The 'total' field correctly reflects post-filter row count."""
        user, token = await self._get_user_and_token(app)
        # 10 rows: 5 with high scores (80+), 5 with low (0-20)
        high = [80.0, 85.0, 90.0, 95.0, 100.0]
        low = [0.0, 5.0, 10.0, 15.0, 20.0]
        await self._insert_analyses(app, user, high + low)

        # Without filter: total=10
        resp_all = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_all.json()["total"] == 10

        # With min_score=50: total=5 (only the high-score rows)
        resp_filtered = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"min_score": 50},
        )
        data = resp_filtered.json()
        assert data["total"] == 5, f"Expected 5 filtered rows, got {data['total']}"
        assert data["pages"] == 1, f"Expected 1 page for 5 rows at per_page=20, got {data['pages']}"

    async def test_min_score_pagination_page_2_no_duplicates(self, app: FastAPI, client: AsyncClient):
        """With min_score filter, page 2 doesn't show rows from page 1.

        This was the original bug: the post-filter 'continue' pattern caused
        pagination offsets to skip filtered-out rows, so page 2 would show
        rows that should have been on page 1 (or skip rows entirely).
        """
        user, token = await self._get_user_and_token(app)
        # 20 rows: first 10 have high scores (85), last 10 low (15)
        high = [85.0] * 10
        low = [15.0] * 10
        await self._insert_analyses(app, user, high + low)

        # min_score=50 should give exactly 10 rows (the high-score ones)
        # At per_page=3, that's 4 pages
        ids_seen: set[int] = set()
        for page in range(1, 5):
            resp = await client.get(
                "/api/v1/history",
                headers={"Authorization": f"Bearer {token}"},
                params={"page": page, "per_page": 3, "min_score": 50},
            )
            data = resp.json()
            assert data["total"] == 10, (
                f"Page {page}: expected total=10, got {data['total']}"
            )
            assert data["pages"] == 4, (
                f"Page {page}: expected pages=4, got {data['pages']}"
            )

            current_ids = {r["id"] for r in data["rows"]}
            # Check no duplicates with previous pages
            dupes = ids_seen & current_ids
            assert not dupes, (
                f"Page {page} has duplicate rows with earlier page(s): {dupes}"
            )
            ids_seen.update(current_ids)

            # Verify all rows on this page have score >= 50
            for row in data["rows"]:
                assert row["score"] is not None and row["score"] >= 50, (
                    f"Row {row['id']} on page {page} has score {row['score']} < 50"
                )

        # Verify we saw exactly 10 unique rows across all pages
        assert len(ids_seen) == 10, (
            f"Expected 10 unique rows across 4 pages, got {len(ids_seen)}"
        )

    async def test_min_score_pagination_high_filter(self, app: FastAPI, client: AsyncClient):
        """min_score=90 with small per_page works across pages."""
        user, token = await self._get_user_and_token(app)
        # 15 rows: 5 with score >= 90, 10 with score < 90
        high = [95.0] * 5
        low = [float(i * 6) for i in range(10)]  # 0, 6, 12, 18, ..., 54
        await self._insert_analyses(app, user, high + low)

        # min_score=90 → total=5
        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"min_score": 90, "per_page": 2},
        )
        d1 = resp.json()
        assert d1["total"] == 5, f"Expected 5 rows >= 90, got {d1['total']}"
        assert d1["pages"] == 3, f"Expected 3 pages, got {d1['pages']}"
        assert len(d1["rows"]) == 2

        # Page 2
        resp2 = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"page": 2, "per_page": 2, "min_score": 90},
        )
        d2 = resp2.json()
        assert d2["page"] == 2
        assert len(d2["rows"]) == 2
        assert d1["rows"][0]["id"] != d2["rows"][0]["id"]

        # Page 3 (last page — 1 row)
        resp3 = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"page": 3, "per_page": 2, "min_score": 90},
        )
        d3 = resp3.json()
        assert d3["page"] == 3
        assert len(d3["rows"]) == 1

        # Verify uniqueness across all pages
        all_ids = (
            {r["id"] for r in d1["rows"]}
            | {r["id"] for r in d2["rows"]}
            | {r["id"] for r in d3["rows"]}
        )
        assert len(all_ids) == 5, f"Expected 5 unique IDs, got {len(all_ids)}"

    # ── Combined filters ──────────────────────────────────────────────

    async def test_min_score_with_symbol_filter(self, app: FastAPI, client: AsyncClient):
        """min_score + symbol filter work together."""
        user, token = await self._get_user_and_token(app)
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            entries = [
                ("BTC-USD", 90.0),
                ("BTC-USD", 30.0),
                ("ETH-USD", 85.0),
                ("ETH-USD", 10.0),
                ("SOL-USD", 95.0),
            ]
            for i, (pair, score) in enumerate(entries):
                session.add(Analysis(
                    user_id=user.id,
                    pair=pair,
                    analysis_type="scan",
                    score=score,
                    result=_make_result_blob(score),
                    created_at=datetime.utcnow() - timedelta(hours=i),
                ))
            await session.commit()

        # BTC-USD with min_score=50 → 1 row (90)
        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbol": "BTC-USD", "min_score": 50},
        )
        data = resp.json()
        assert data["total"] == 1
        assert data["rows"][0]["score"] == 90

        # ETH-USD with min_score=50 → 1 row (85)
        resp2 = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbol": "ETH-USD", "min_score": 50},
        )
        assert resp2.json()["total"] == 1

        # SOL-USD with min_score=80 → 1 row (95)
        resp3 = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbol": "SOL-USD", "min_score": 80},
        )
        assert resp3.json()["total"] == 1

    async def test_min_score_with_date_filter(self, app: FastAPI, client: AsyncClient):
        """min_score + date range work together."""
        user, token = await self._get_user_and_token(app)
        from backend.database import get_session_factory

        factory = get_session_factory()
        now = datetime.utcnow()
        async with factory() as session:
            entries = [
                (90.0, now - timedelta(hours=1)),
                (30.0, now - timedelta(hours=2)),
                (85.0, now - timedelta(hours=3)),
                (10.0, now - timedelta(hours=4)),
            ]
            for score, ts in entries:
                session.add(Analysis(
                    user_id=user.id,
                    pair="DATE-FILTER",
                    analysis_type="scan",
                    score=score,
                    result=_make_result_blob(score),
                    created_at=ts,
                ))
            await session.commit()

        # Wide date range + min_score=50 → 2 rows (90, 85)
        from_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"from_date": from_date, "to_date": to_date, "min_score": 50},
        )
        data = resp.json()
        assert data["total"] == 2, f"Expected 2 rows, got {data['total']}"
        for row in data["rows"]:
            assert row["score"] >= 50

    # ── Response shape ────────────────────────────────────────────────

    async def test_response_shape(self, app: FastAPI, client: AsyncClient):
        """Response includes all required fields."""
        user, token = await self._get_user_and_token(app)
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            session.add(Analysis(
                user_id=user.id,
                pair="SHAPE-USD",
                analysis_type="scan",
                score=75.0,
                result=_make_result_blob(75.0),
                created_at=datetime.utcnow(),
            ))
            await session.commit()

        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
        assert "rows" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert "pages" in data
        assert len(data["rows"]) == 1
        row = data["rows"][0]
        assert "id" in row
        assert "symbol" in row
        assert "analysis_type" in row
        assert "score" in row
        assert "direction" in row
        assert "alert_sent" in row
        assert "created_at" in row
        assert row["symbol"] == "SHAPE-USD"
        assert row["score"] == 75.0
        assert row["direction"] == "LONG"

    # ── Edge cases ────────────────────────────────────────────────────

    async def test_min_score_above_all(self, app: FastAPI, client: AsyncClient):
        """min_score higher than any existing score returns empty."""
        user, token = await self._get_user_and_token(app)
        await self._insert_analyses(app, user, [10, 20, 30, 40, 50])

        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"min_score": 100},
        )
        data = resp.json()
        assert data["total"] == 0
        assert data["rows"] == []
        assert data["pages"] == 1

    async def test_delete_analysis(self, app: FastAPI, client: AsyncClient):
        """DELETE /api/v1/history/{id} removes an analysis."""
        user, token = await self._get_user_and_token(app)
        await self._insert_analyses(app, user, [50.0])

        # Get the id
        resp = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        analysis_id = resp.json()["rows"][0]["id"]

        # Delete it
        del_resp = await client.delete(
            f"/api/v1/history/{analysis_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True

        # Verify it's gone
        resp2 = await client.get(
            "/api/v1/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.json()["total"] == 0
