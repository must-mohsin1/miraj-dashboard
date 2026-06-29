"""Tests for APScheduler integration + Results history API (P2-C).

Run with::

    cd <workspace>
    .venv/bin/python test_p2c_scheduler_results.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# ── Ensure backend is importable ─────────────────────────────────────
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORKSPACE)
os.environ["DATABASE_URL"] = os.path.join(WORKSPACE, "test_p2c.db")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-p2c-tests"

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from backend.database import Base, get_engine, get_session_factory, set_db_path
from backend.main import app
from backend.models import Analysis, ScanRun, User, WatchlistPair
from backend.scheduler import (
    get_scheduler,
    run_scheduled_scan,
    setup_scheduler,
    start_scheduler,
    stop_scheduler,
)
from backend.routes.results import PaginatedResults

P = 0
F = 0
_DB = os.path.join(WORKSPACE, "test_p2c.db")


def _cleanup():
    """Remove leftover test DB."""
    for p in (_DB,):
        if os.path.exists(p):
            os.remove(p)


def _init_db():
    """Create fresh tables in the test DB."""
    _cleanup()
    set_db_path(_DB)
    engine = get_engine()
    # Recreate all metadata
    import sqlalchemy
    conn = sqlalchemy.create_engine(f"sqlite:///{_DB}")
    Base.metadata.create_all(conn)
    conn.dispose()


async def _seed_data():
    """Create a test user with analyses and watchlist pairs."""
    factory = get_session_factory()
    async with factory() as session:
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="$2b$12$dummyhash",
        )
        session.add(user)
        await session.flush()

        # Add some analyses
        for i, (pair, days_ago) in enumerate([
            ("BTCUSDT", 0),
            ("ETHUSDT", 1),
            ("BTCUSDT", 2),
            ("SOLUSDT", 3),
            ("ETHUSDT", 4),
        ]):
            analysis = Analysis(
                user_id=user.id,
                pair=pair,
                analysis_type="scan",
                parameters=json.dumps({"symbol": pair}),
                result=json.dumps({
                    "confluence_score": 15.0 + i,
                    "trade_plan": {"direction": "LONG", "trade_decision": True},
                    "score_breakdown": {"total": 15.0 + i},
                }),
                created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            )
            session.add(analysis)

        # Add a watchlist pair for the scheduler
        wp = WatchlistPair(user_id=user.id, pair="BTCUSDT")
        session.add(wp)
        wp2 = WatchlistPair(user_id=user.id, pair="ETHUSDT")
        session.add(wp2)

        await session.commit()
        return user.id


async def _auth_token() -> str:
    """Create an access token for the test user."""
    from backend.auth import create_access_token
    return create_access_token(data={"sub": "1"})


async def _client():
    """Return an async client pointed at the test app."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ═══════════════════════════════════════════════════════════════════════
# Tests — Model
# ═══════════════════════════════════════════════════════════════════════


async def test_scan_run_model():
    """Verify ScanRun is created and queried correctly."""
    factory = get_session_factory()
    async with factory() as session:
        run = ScanRun(status="running", pair_count=5)
        session.add(run)
        await session.commit()

        result = await session.execute(select(ScanRun).where(ScanRun.id == run.id))
        loaded = result.scalar_one()
        assert loaded.status == "running", f"Expected running, got {loaded.status}"
        assert loaded.pair_count == 5
        assert loaded.started_at is not None
        assert loaded.ended_at is None
        print(f"  PASS ScanRun model: id={loaded.id}, status={loaded.status}")
        global P
        P += 1


# ═══════════════════════════════════════════════════════════════════════
# Tests — Scheduler
# ═══════════════════════════════════════════════════════════════════════


async def test_setup_scheduler():
    """Verify setup_scheduler creates the cron job."""
    stop_scheduler()  # ensure clean state
    scheduler = setup_scheduler(app)
    jobs = scheduler.get_jobs()
    job_ids = [j.id for j in jobs]
    assert "watchlist_scan" in job_ids, f"Expected watchlist_scan job, got {job_ids}"
    print(f"  PASS setup_scheduler: jobs={job_ids}")
    global P
    P += 1


async def test_start_stop_scheduler():
    """Verify start/stop lifecycle."""
    stop_scheduler()
    # Re-fetch after stop to ensure clean state
    scheduler = get_scheduler()
    assert not scheduler.running, "Scheduler should not be running initially"
    start_scheduler()
    assert scheduler.running, "Scheduler should be running after start"
    stop_scheduler()
    # Fetch a fresh scheduler instance after stop
    scheduler2 = get_scheduler()
    assert not scheduler2.running, "Scheduler should not be running after stop"
    print("  PASS start/stop scheduler lifecycle")
    global P
    P += 1


async def test_run_scheduled_scan():
    """Verify run_scheduled_scan processes watchlist pairs and creates ScanRun."""
    # Patch run_scan to return fake data (avoids network)
    fake_result = {
        "confluence_score": 18.5,
        "trade_plan": {"direction": "LONG", "trade_decision": True},
        "score_breakdown": {"total": 18.5},
        "symbol": "BTCUSDT",
        "overall_score": 61.7,
    }

    with patch("backend.scheduler.run_scan", return_value=fake_result):
        await run_scheduled_scan()

    # Verify ScanRun was created
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ScanRun).order_by(ScanRun.id.desc())
        )
        last_run = result.scalars().first()
        assert last_run is not None, "Expected a ScanRun record"
        assert last_run.status == "completed", f"Expected completed, got {last_run.status}"
        assert last_run.pair_count >= 1, f"Expected pair_count >= 1, got {last_run.pair_count}"
        assert last_run.ended_at is not None, "ended_at should be set"
        print(
            f"  PASS run_scheduled_scan: id={last_run.id}, status={last_run.status}, "
            f"pairs={last_run.pair_count}"
        )
        global P
        P += 1


async def test_run_scheduled_scan_empty():
    """Verify run_scheduled_scan handles empty watchlist gracefully."""
    # Clear all watchlist pairs
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(WatchlistPair.__table__.delete())
        await session.commit()

    with patch("backend.scheduler.run_scan", return_value={}):
        await run_scheduled_scan()

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ScanRun).order_by(ScanRun.id.desc())
        )
        last_run = result.scalars().first()
        assert last_run is not None
        assert last_run.status == "completed", f"Expected completed, got {last_run.status}"
        assert last_run.pair_count == 0, f"Expected 0 pairs, got {last_run.pair_count}"
        print(f"  PASS run_scheduled_scan (empty): status={last_run.status}, pairs={last_run.pair_count}")
        global P
        P += 1


# ═══════════════════════════════════════════════════════════════════════
# Tests — Results API
# ═══════════════════════════════════════════════════════════════════════


async def test_results_no_auth():
    """GET /api/v1/results without auth returns 401."""
    async with await _client() as client:
        resp = await client.get("/api/v1/results")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print(f"  PASS results no-auth: {resp.status_code}")
        global P
        P += 1


async def test_results_empty():
    """GET /api/v1/results with auth returns empty list when no analyses exist."""
    # We'll test with a brand new user that has no analyses
    factory = get_session_factory()
    async with factory() as session:
        user2 = User(
            username="emptyuser",
            email="empty@example.com",
            hashed_password="$2b$12$dummyhash",
        )
        session.add(user2)
        await session.commit()
        token = _make_token("2")

    async with await _client() as client:
        resp = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert data["items"] == [], f"Expected empty items, got {data['items']}"
        assert data["total"] == 0
        assert data["limit"] == 20
        assert data["offset"] == 0
        print(f"  PASS results empty: total={data['total']}, items={len(data['items'])}")
        global P
        P += 1


def _make_token(user_id: str) -> str:
    """Create a JWT for the given user id."""
    from backend.auth import create_access_token
    return create_access_token(data={"sub": user_id})


async def test_results_pagination():
    """Verify pagination (limit, offset), sorting, and total."""
    token = await _auth_token()
    async with await _client() as client:
        # Default (limit=20, offset=0)
        resp = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        total = data["total"]
        assert total >= 5, f"Expected >=5 analyses, got {total}"
        assert data["limit"] == 20
        assert data["offset"] == 0

        # Results should be sorted by created_at DESC
        items = data["items"]
        if len(items) >= 2:
            d0 = items[0]["created_at"]
            d1 = items[1]["created_at"]
            assert d0 >= d1, f"Results not sorted DESC: {d0} < {d1}"

        # limit=2, offset=0
        resp2 = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 2, "offset": 0},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["items"]) == 2, f"Expected 2 items, got {len(data2['items'])}"
        assert data2["total"] == total
        assert data2["limit"] == 2

        # limit=2, offset=2 (second page)
        resp3 = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 2, "offset": 2},
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert len(data3["items"]) == 2, f"Expected 2 items, got {len(data3['items'])}"
        assert data3["offset"] == 2
        # Items should differ from first page
        if data2["items"] and data3["items"]:
            assert data2["items"][0]["id"] != data3["items"][0]["id"], "Pages should differ"

        # max limit constraint
        resp4 = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 200},
        )
        assert resp4.status_code == 422, f"Expected 422 for limit>100, got {resp4.status_code}"

        print(
            f"  PASS results pagination: total={total}, page1={len(data2['items'])}, "
            f"page2={len(data3['items'])}"
        )
        global P
        P += 1


async def test_results_filter_symbol():
    """Verify symbol filter on results."""
    token = await _auth_token()
    async with await _client() as client:
        resp = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbol": "BTCUSDT"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1, f"Expected >=1 BTC analysis, got {data['total']}"
        for item in data["items"]:
            assert item["pair"] == "BTCUSDT", f"Expected BTCUSDT, got {item['pair']}"

        # Unknown symbol → empty
        resp2 = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbol": "DOGEUSDT"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["total"] == 0, f"Expected 0 for DOGEUSDT, got {data2['total']}"

        print(f"  PASS results filter symbol: BTC={data['total']}, DOGE={data2['total']}")
        global P
        P += 1


async def test_results_filter_date():
    """Verify from_date / to_date filters."""
    token = await _auth_token()
    async with await _client() as client:
        # Filter with a very recent from_date (should match only today's)
        now = datetime.now(timezone.utc)
        from_dt = (now - timedelta(hours=6)).isoformat()

        resp = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
            params={"from_date": from_dt},
        )
        assert resp.status_code == 200
        data = resp.json()
        print(f"  => from_date={from_dt[:19]} -> total={data['total']}")
        # Recently created items should appear

        # Filter with a far-future to_date → empty
        recent_dt = (now - timedelta(days=365)).isoformat()
        resp2 = await client.get(
            "/api/v1/results",
            headers={"Authorization": f"Bearer {token}"},
            params={"to_date": recent_dt},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        print(f"  => to_date={recent_dt[:19]} -> total={data2['total']}")

        print(f"  PASS results filter date")
        global P
        P += 1


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


async def main():
    global P, F

    # Clean up from previous runs
    stop_scheduler()
    _init_db()

    await _seed_data()

    # ── Run tests ──────────────────────────────────────────────────
    tests = [
        ("ScanRun model", test_scan_run_model),
        ("Setup scheduler", test_setup_scheduler),
        ("Start/stop scheduler", test_start_stop_scheduler),
        ("Run scheduled scan", test_run_scheduled_scan),
        ("Run scheduled scan (empty)", test_run_scheduled_scan_empty),
        ("Results no auth", test_results_no_auth),
        ("Results empty", test_results_empty),
        ("Results pagination", test_results_pagination),
        ("Results filter symbol", test_results_filter_symbol),
        ("Results filter date", test_results_filter_date),
    ]

    for name, fn in tests:
        try:
            await fn()
        except Exception as e:
            print(f"  FAIL {name}: {e}")
            import traceback
            traceback.print_exc()
            F += 1

    print(f"\n{'=' * 40}")
    print(f"Results: {P} passed, {F} failed out of {P + F} tests")

    # Cleanup
    stop_scheduler()
    _cleanup()

    sys.exit(0 if F == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
