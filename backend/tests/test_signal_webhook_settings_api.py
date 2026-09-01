"""Authenticated Settings API coverage for signed webhook channels."""

from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend.auth import create_access_token, hash_password
from backend.database import Base, get_engine, get_session_factory, set_db_path
from backend.models import AlertChannel, User


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def app(tmp_path) -> AsyncGenerator[FastAPI, None]:
    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(str(tmp_path / "signal_webhook_settings.db"))

    from backend.main import app as main_app

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield main_app
    await get_engine().dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as async_client:
        yield async_client


async def _create_user_and_token() -> tuple[User, str]:
    factory = get_session_factory()
    async with factory() as session:
        user = User(
            username="webhook-settings-user",
            email="webhook-settings@example.com",
            hashed_password=hash_password("testpass123"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user, create_access_token(data={"sub": str(user.id)})


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_webhook_channel_create_list_update_and_toggle_never_expose_secret(
    client: AsyncClient,
):
    user, token = await _create_user_and_token()
    destination = AsyncMock(return_value=("https://hooks.example.com/miraj", "s" * 32))
    original_config = {
        "webhook_url": "https://hooks.example.com/miraj",
        "signing_secret": "s" * 32,
    }

    with patch(
        "backend.routes.settings.validate_webhook_destination",
        destination,
    ):
        created = await client.post(
            "/api/v1/settings/channels",
            json={
                "channel_type": "webhook",
                "config": original_config,
                "enabled": True,
            },
            headers=_headers(token),
        )

        assert created.status_code == 201
        channel_id = created.json()["id"]
        assert created.json()["config"] == {
            "webhook_url": original_config["webhook_url"],
            "has_signing_secret": True,
        }
        assert '"signing_secret"' not in created.text

        listed = await client.get(
            "/api/v1/settings/channels",
            headers=_headers(token),
        )
        assert listed.status_code == 200
        assert listed.json()["channels"][0]["config"] == {
            "webhook_url": original_config["webhook_url"],
            "has_signing_secret": True,
        }
        assert '"signing_secret"' not in listed.text

        rotated_config = {
            "webhook_url": "https://automation.example.com/miraj",
            "signing_secret": "r" * 32,
        }
        updated = await client.put(
            f"/api/v1/settings/channels/{channel_id}",
            json={"config": rotated_config},
            headers=_headers(token),
        )
        assert updated.status_code == 200
        assert updated.json()["config"] == {
            "webhook_url": rotated_config["webhook_url"],
            "has_signing_secret": True,
        }
        assert '"signing_secret"' not in updated.text

        toggled = await client.put(
            f"/api/v1/settings/channels/{channel_id}",
            json={"enabled": False},
            headers=_headers(token),
        )
        assert toggled.status_code == 200
        assert toggled.json()["enabled"] is False
        assert toggled.json()["config"]["has_signing_secret"] is True
        assert '"signing_secret"' not in toggled.text

    assert destination.await_count == 2
    factory = get_session_factory()
    async with factory() as session:
        stored = await session.get(AlertChannel, channel_id)
        assert stored.user_id == user.id
        assert json.loads(stored.config) == rotated_config
        assert stored.enabled == 0


async def test_webhook_channel_rejects_unsafe_destination_without_persisting(
    client: AsyncClient,
):
    user, token = await _create_user_and_token()
    with patch(
        "backend.routes.settings.validate_webhook_destination",
        AsyncMock(side_effect=ValueError("unsafe destination")),
    ):
        response = await client.post(
            "/api/v1/settings/channels",
            json={
                "channel_type": "webhook",
                "config": {
                    "webhook_url": "https://hooks.example.com/miraj",
                    "signing_secret": "s" * 32,
                },
            },
            headers=_headers(token),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "unsafe destination"
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(AlertChannel).where(AlertChannel.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


async def test_webhook_channel_rejects_invalid_update_without_overwriting_config(
    client: AsyncClient,
):
    user, token = await _create_user_and_token()
    original_config = {
        "webhook_url": "https://hooks.example.com/miraj",
        "signing_secret": "s" * 32,
    }
    factory = get_session_factory()
    async with factory() as session:
        channel = AlertChannel(
            user_id=user.id,
            channel_type="webhook",
            config=json.dumps(original_config),
            enabled=1,
        )
        session.add(channel)
        await session.commit()
        await session.refresh(channel)
        channel_id = channel.id

    with patch(
        "backend.routes.settings.validate_webhook_destination",
        AsyncMock(side_effect=ValueError("unsafe destination")),
    ):
        response = await client.put(
            f"/api/v1/settings/channels/{channel_id}",
            json={
                "config": {
                    "webhook_url": "https://rebound.example.com/miraj",
                    "signing_secret": "r" * 32,
                }
            },
            headers=_headers(token),
        )

    assert response.status_code == 422
    async with factory() as session:
        stored = await session.get(AlertChannel, channel_id)
        assert json.loads(stored.config) == original_config


async def test_settings_schema_rejects_unknown_channel_type(client: AsyncClient):
    _, token = await _create_user_and_token()
    response = await client.post(
        "/api/v1/settings/channels",
        json={"channel_type": "broker", "config": {}},
        headers=_headers(token),
    )

    assert response.status_code == 422


async def test_settings_schema_rejects_retired_discord_channel_type(client: AsyncClient):
    _, token = await _create_user_and_token()
    response = await client.post(
        "/api/v1/settings/channels",
        json={
            "channel_type": "discord",
            "config": {"webhook_url": "https://discord.com/api/webhooks/xxx"},
        },
        headers=_headers(token),
    )

    assert response.status_code == 422


async def test_webhook_channel_limit_rejects_before_dns_validation(client: AsyncClient):
    _, token = await _create_user_and_token()
    destination = AsyncMock()
    with (
        patch("backend.routes.settings.MAX_WEBHOOK_CHANNELS_PER_USER", 0),
        patch(
            "backend.routes.settings.validate_webhook_destination",
            destination,
        ),
    ):
        response = await client.post(
            "/api/v1/settings/channels",
            json={
                "channel_type": "webhook",
                "config": {
                    "webhook_url": "https://hooks.example.com/miraj",
                    "signing_secret": "s" * 32,
                },
            },
            headers=_headers(token),
        )

    assert response.status_code == 409
    destination.assert_not_awaited()


async def test_list_webhook_channel_fails_closed_for_malformed_stored_config(
    client: AsyncClient,
):
    user, token = await _create_user_and_token()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            AlertChannel(
                user_id=user.id,
                channel_type="webhook",
                config="not-json",
                enabled=1,
            )
        )
        await session.commit()

    response = await client.get(
        "/api/v1/settings/channels",
        headers=_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["channels"][0]["config"] == {
        "has_signing_secret": False,
    }


async def test_webhook_channel_limit_is_enforced_under_concurrent_creates(
    client: AsyncClient,
):
    user, token = await _create_user_and_token()
    request = {
        "channel_type": "webhook",
        "config": {
            "webhook_url": "https://hooks.example.com/miraj",
            "signing_secret": "s" * 32,
        },
    }
    with (
        patch("backend.routes.settings.MAX_WEBHOOK_CHANNELS_PER_USER", 1),
        patch(
            "backend.routes.settings.validate_webhook_destination",
            AsyncMock(return_value=("https://hooks.example.com/miraj", "s" * 32)),
        ),
    ):
        responses = await asyncio.gather(
            client.post(
                "/api/v1/settings/channels",
                json=request,
                headers=_headers(token),
            ),
            client.post(
                "/api/v1/settings/channels",
                json=request,
                headers=_headers(token),
            ),
        )

    assert sorted(response.status_code for response in responses) == [201, 409]
    factory = get_session_factory()
    async with factory() as session:
        channels = (
            (
                await session.execute(
                    select(AlertChannel).where(AlertChannel.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(channels) == 1
