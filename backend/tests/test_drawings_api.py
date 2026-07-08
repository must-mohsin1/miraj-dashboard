"""Tests for the chart drawings API contract.

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_drawings_api.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import AsyncGenerator, Generator
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.auth import create_access_token, hash_password
from backend.database import Base, set_db_path
from backend.models import User


pytestmark = pytest.mark.anyio


def _make_app() -> FastAPI:
    from backend.main import app

    return app


async def _create_user(session, username: str = "testuser", email: str = "test@example.com") -> User:
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
    return create_access_token(data={"sub": str(user_id)})


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> Generator[str, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="drawings_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def app(tmp_db_path: str) -> FastAPI:
    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None

    set_db_path(tmp_db_path)
    app = _make_app()

    from backend.database import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_drawings_endpoint_returns_graceful_empty_contract(
    app: FastAPI, client: AsyncClient
):
    from backend.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        user = await _create_user(session)
        await session.commit()
        token = _token_for(cast(int, user.id))

    resp = await client.get(
        "/api/v1/drawings?symbol=BTC-USD&timeframe=1d",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "symbol": "BTC-USD",
        "timeframe": "1d",
        "drawings": [],
        "total": 0,
    }


async def test_drawings_endpoint_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/drawings?symbol=BTC-USD&timeframe=1d")

    assert resp.status_code == 401


async def test_drawings_endpoint_validates_timeframe(app: FastAPI, client: AsyncClient):
    from backend.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        user = await _create_user(session, username="tfuser", email="tf@example.com")
        await session.commit()
        token = _token_for(cast(int, user.id))

    resp = await client.get(
        "/api/v1/drawings?symbol=BTC-USD&timeframe=10y",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 422
