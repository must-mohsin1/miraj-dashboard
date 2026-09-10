"""Authentication API regression coverage."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend.database import Base, get_engine, set_db_path
from backend.routes.auth import router as auth_router

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def app(tmp_path) -> AsyncGenerator[FastAPI, None]:
    set_db_path(str(tmp_path / "auth_api.db"))
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    auth_app = FastAPI()
    auth_app.include_router(auth_router)
    yield auth_app

    await get_engine().dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client


async def test_login_accepts_registered_email_case_insensitively(
    client: AsyncClient,
) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "email-login-user",
            "email": "Email.Login@Example.com",
            "password": "testpass123",
        },
    )
    assert registration.status_code == 201, registration.text

    login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "email.login@example.com",
            "password": "testpass123",
        },
    )

    assert login.status_code == 200, login.text
    assert login.json()["token_type"] == "bearer"
    assert login.json()["access_token"]
