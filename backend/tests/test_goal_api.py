"""Goal API rollover behavior."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import get_current_user, hash_password
from backend.database import Base, get_session, set_db_path
from backend.models import ExchangeSyncState, FuturesAccountSnapshot, MonthlyProfitGoal, User
from backend.routes.goal import router as goal_router
from backend.services.goal_service import upsert_open_goal

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="goal_api_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def session(tmp_db_path: str):
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(tmp_db_path)
    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = database.get_session_factory()
    async with factory() as current:
        yield current


async def test_get_closes_old_month_and_reports_new_month(
    session, monkeypatch: pytest.MonkeyPatch
):
    user = User(
        username="goal-api-user",
        email="goal-api@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(
            ExchangeSyncState(
                user_id=user.id,
                exchange="mexc",
                stream=stream,
                status="fresh",
                complete=True,
                rows_fetched_total=0,
                updated_at=datetime(2026, 8, 31),
            )
        )
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id,
                exchange="mexc",
                settlement_asset="USDT",
                equity=1000.0,
                source_ts=datetime(2026, 8, 2, 10, 0),
                synced_at=datetime(2026, 8, 2, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id,
                exchange="mexc",
                settlement_asset="USDT",
                equity=1100.0,
                source_ts=datetime(2026, 8, 31, 10, 0),
                synced_at=datetime(2026, 8, 31, 10, 0),
            ),
        ]
    )
    await session.flush()
    goal = await upsert_open_goal(
        session,
        user.id,
        "mexc",
        target_return_pct=8.0,
        redeem_pct=40.0,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    await session.commit()

    fixed_now = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr("backend.services.goal_service.datetime", FrozenDateTime)

    app = FastAPI()
    app.include_router(goal_router)

    async def current_user_override():
        return user

    async def session_override():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_session] = session_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/goal/now?exchange=mexc")

    assert response.status_code == 200
    payload = response.json()
    assert (payload["period_year"], payload["period_month"]) == (2026, 9)
    assert payload["state"] == "NO_GOAL"
    assert payload["goal"] is None
    assert payload["progress"]["return_pct"] is None
    assert payload["period_analytics"]["reason"] == "goal_not_set"
    assert payload["year_archive"] == [
        {
            "period_year": 2026,
            "period_month": 8,
            "status": "closed",
            "target_return_pct": 8.0,
            "realized_return_pct": 10.0,
            "net_profit": 100.0,
            "declared_redeem_usd": 40.0,
            "declared_reinvest_usd": 60.0,
            "closed_at": "2026-09-02T08:00:00Z",
        }
    ]

    archived = (
        await session.execute(select(MonthlyProfitGoal).where(MonthlyProfitGoal.id == goal.id))
    ).scalar_one()
    assert archived.status == "closed"


async def test_put_closes_old_month_before_opening_new_goal(
    session, monkeypatch: pytest.MonkeyPatch
):
    user = User(
        username="goal-put-user",
        email="goal-put@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    for stream in ("deposits", "withdrawals", "futures_transfers"):
        session.add(
            ExchangeSyncState(
                user_id=user.id,
                exchange="mexc",
                stream=stream,
                status="fresh",
                complete=True,
                rows_fetched_total=0,
                updated_at=datetime(2026, 8, 31),
            )
        )
    session.add_all(
        [
            FuturesAccountSnapshot(
                user_id=user.id,
                exchange="mexc",
                settlement_asset="USDT",
                equity=1000.0,
                source_ts=datetime(2026, 8, 2, 10, 0),
                synced_at=datetime(2026, 8, 2, 10, 0),
            ),
            FuturesAccountSnapshot(
                user_id=user.id,
                exchange="mexc",
                settlement_asset="USDT",
                equity=1100.0,
                source_ts=datetime(2026, 8, 31, 10, 0),
                synced_at=datetime(2026, 8, 31, 10, 0),
            ),
        ]
    )
    await session.flush()
    august_goal = await upsert_open_goal(
        session,
        user.id,
        "mexc",
        target_return_pct=8.0,
        redeem_pct=40.0,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    await session.commit()

    fixed_now = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr("backend.services.goal_service.datetime", FrozenDateTime)

    app = FastAPI()
    app.include_router(goal_router)

    async def current_user_override():
        return user

    async def session_override():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_session] = session_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/api/v1/goal/now",
            json={
                "exchange": "MEXC",
                "target_return_pct": 12.0,
                "redeem_pct": 25.0,
                "base_equity": 1100.0,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert (payload["period_year"], payload["period_month"]) == (2026, 9)
    assert payload["goal"]["status"] == "open"
    assert payload["goal"]["target_return_pct"] == pytest.approx(12.0)

    goals = list(
        (
            await session.execute(
                select(MonthlyProfitGoal)
                .where(MonthlyProfitGoal.user_id == user.id)
                .order_by(MonthlyProfitGoal.period_year, MonthlyProfitGoal.period_month)
            )
        ).scalars().all()
    )
    assert [(goal.period_year, goal.period_month, goal.status) for goal in goals] == [
        (2026, 8, "closed"),
        (2026, 9, "open"),
    ]
    assert august_goal.status == "closed"
    assert sum(goal.status == "open" for goal in goals) == 1
