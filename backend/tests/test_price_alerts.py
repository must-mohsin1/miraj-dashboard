"""Tests for the Price Alert feature.

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_price_alerts.py -v

Tests cover:
- PriceAlert CRUD via API (create, list, get, cancel, delete)
- Price alert service: create, cancel, list, get, delete
- Trigger logic: above/below direction, price checks
- Message formatting for Telegram and Discord
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import time)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.database import Base, get_session, set_db_path
from backend.main import app
from backend.models import AlertChannel, PriceAlert, User
from backend.services.price_alert_service import (
    _build_price_alert_embed,
    _format_price_alert_message,
    cancel_price_alert,
    check_price_alerts,
    create_price_alert,
    delete_price_alert,
    get_price_alert,
    list_price_alerts,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


pytestmark = pytest.mark.anyio


@pytest.fixture
def tmp_db_path() -> str:
    """Yield a unique temporary DB path per test, cleaned up after."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="price_alert_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def app(tmp_db_path: str):
    """Return a fully-initialized FastAPI app pointed at *tmp_db_path*."""
    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None

    set_db_path(tmp_db_path)

    from backend.main import app as _app

    # Create tables
    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return _app


@pytest.fixture
async def session(tmp_db_path: str):
    """Yield an async session backed by a fresh DB with all tables."""
    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None

    set_db_path(tmp_db_path)

    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = database.get_session_factory()
    async with factory() as s:
        yield s


@pytest.fixture
async def user(session) -> User:
    """Create and return a test user."""
    from backend.auth import hash_password

    user = User(
        username="pricealertuser",
        email="pricealert@test.com",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


# ── Shared helpers for API tests ─────────────────────────────────────────────


async def _create_api_user(session) -> tuple[User, str]:
    """Create a user and return (user, JWT token)."""
    from backend.auth import create_access_token, hash_password

    user = User(
        username="apiuser",
        email="api@test.com",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return user, token


@pytest.fixture
async def alert(session, user) -> PriceAlert:
    """Create and return a test price alert."""
    a = await create_price_alert(
        session=session,
        user_id=user.id,
        symbol="BTC-USD",
        price_level=70000.0,
        direction="above",
        message="Moon shot!",
    )
    return a


# ── Service layer tests ─────────────────────────────────────────────────────


class TestPriceAlertService:
    """Unit tests for price_alert_service functions."""

    async def test_create_alert(self, session, user):
        """Creating a price alert persists it with active status."""
        alert = await create_price_alert(
            session=session,
            user_id=user.id,
            symbol="BTC-USD",
            price_level=70000.0,
            direction="above",
            message="Test alert",
        )
        assert alert.id is not None
        assert alert.user_id == user.id
        assert alert.symbol == "BTC-USD"
        assert alert.price_level == 70000.0
        assert alert.direction == "above"
        assert alert.status == "active"
        assert alert.message == "Test alert"
        assert alert.alert_type == "price"

    async def test_create_alert_normalizes_symbol(self, session, user):
        """Symbol should be uppercased and stripped."""
        alert = await create_price_alert(
            session=session,
            user_id=user.id,
            symbol="  eth-usd  ",
            price_level=3000.0,
            direction="below",
        )
        assert alert.symbol == "ETH-USD"

    async def test_list_alerts(self, session, user):
        """list_price_alerts returns user's alerts ordered by created_at desc."""
        a1 = await create_price_alert(session, user.id, "BTC-USD", 70000.0, "above")
        a2 = await create_price_alert(session, user.id, "ETH-USD", 3000.0, "below")
        alerts = await list_price_alerts(session, user.id)
        assert len(alerts) == 2
        # Most recent first
        assert alerts[0].id >= alerts[1].id

    async def test_list_alerts_filter_by_status(self, session, user):
        """list_price_alerts supports status filter."""
        a1 = await create_price_alert(session, user.id, "BTC-USD", 70000.0, "above")
        await cancel_price_alert(session, a1.id, user.id)

        active = await list_price_alerts(session, user.id, status="active")
        cancelled = await list_price_alerts(session, user.id, status="cancelled")
        triggered = await list_price_alerts(session, user.id, status="triggered")

        assert len(active) == 0
        assert len(cancelled) == 1
        assert len(triggered) == 0

    async def test_get_alert(self, session, user):
        """get_price_alert returns the alert scoped to user."""
        a = await create_price_alert(session, user.id, "BTC-USD", 70000.0, "above")
        found = await get_price_alert(session, a.id, user.id)
        assert found is not None
        assert found.id == a.id

    async def test_get_alert_wrong_user(self, session, user):
        """get_price_alert returns None when alert belongs to another user."""
        from backend.auth import hash_password

        other = User(
            username="other", email="other@test.com",
            hashed_password=hash_password("pass"),
        )
        session.add(other)
        await session.flush()
        await session.refresh(other)

        a = await create_price_alert(session, other.id, "BTC-USD", 70000.0, "above")
        found = await get_price_alert(session, a.id, user.id)
        assert found is None

    async def test_cancel_alert(self, session, user):
        """cancel_price_alert sets status to cancelled."""
        a = await create_price_alert(session, user.id, "BTC-USD", 70000.0, "above")
        cancelled = await cancel_price_alert(session, a.id, user.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"

    async def test_cancel_alert_not_found(self, session, user):
        """cancel_price_alert returns None for non-existent alert."""
        result = await cancel_price_alert(session, 9999, user.id)
        assert result is None

    async def test_delete_alert(self, session, user):
        """delete_price_alert permanently removes the alert."""
        a = await create_price_alert(session, user.id, "BTC-USD", 70000.0, "above")
        deleted = await delete_price_alert(session, a.id, user.id)
        assert deleted is True
        # Verify it's gone
        remaining = await list_price_alerts(session, user.id)
        assert len(remaining) == 0

    async def test_delete_alert_not_found(self, session, user):
        """delete_price_alert returns False for non-existent alert."""
        result = await delete_price_alert(session, 9999, user.id)
        assert result is False


# ── Trigger logic tests ────────────────────────────────────────────────────


class TestPriceAlertTrigger:
    """Tests for the check_price_alerts trigger logic."""

    async def test_check_price_above_triggered(self, session, user):
        """Alert with direction='above' triggers when price >= level."""
        a = await create_price_alert(
            session, user.id, "BTC-USD",
            price_level=50000.0, direction="above",
        )

        # Mock check_single_price to return 55000 (above level)
        with patch(
            "backend.services.price_alert_service.check_single_price",
            new_callable=AsyncMock,
            return_value=55000.0,
        ):
            outcomes = await check_price_alerts(session)

        assert len(outcomes) == 1
        assert outcomes[0]["alert_id"] == a.id
        assert outcomes[0]["status"] == "triggered"
        assert outcomes[0]["current_price"] == 55000.0

        # Alert should be marked triggered in DB
        refreshed = await get_price_alert(session, a.id, user.id)
        assert refreshed is not None
        assert refreshed.status == "triggered"
        assert refreshed.current_price == 55000.0
        assert refreshed.triggered_at is not None

    async def test_check_price_below_triggered(self, session, user):
        """Alert with direction='below' triggers when price <= level."""
        a = await create_price_alert(
            session, user.id, "ETH-USD",
            price_level=4000.0, direction="below",
        )

        with patch(
            "backend.services.price_alert_service.check_single_price",
            new_callable=AsyncMock,
            return_value=3500.0,  # below level
        ):
            outcomes = await check_price_alerts(session)

        assert len(outcomes) == 1
        assert outcomes[0]["alert_id"] == a.id
        assert outcomes[0]["status"] == "triggered"

    async def test_check_price_not_triggered(self, session, user):
        """Alert does NOT trigger when price hasn't crossed the level."""
        a = await create_price_alert(
            session, user.id, "BTC-USD",
            price_level=70000.0, direction="above",
        )

        with patch(
            "backend.services.price_alert_service.check_single_price",
            new_callable=AsyncMock,
            return_value=65000.0,  # below level
        ):
            outcomes = await check_price_alerts(session)

        assert len(outcomes) == 0

        # Alert should still be active
        refreshed = await get_price_alert(session, a.id, user.id)
        assert refreshed is not None
        assert refreshed.status == "active"

    async def test_check_price_exact_match_above(self, session, user):
        """Trigger when price equals the level exactly (above direction)."""
        a = await create_price_alert(
            session, user.id, "BTC-USD",
            price_level=65000.0, direction="above",
        )

        with patch(
            "backend.services.price_alert_service.check_single_price",
            new_callable=AsyncMock,
            return_value=65000.0,  # exactly at level
        ):
            outcomes = await check_price_alerts(session)

        assert len(outcomes) == 1
        assert outcomes[0]["status"] == "triggered"

    async def test_check_price_exact_match_below(self, session, user):
        """Trigger when price equals the level exactly (below direction)."""
        a = await create_price_alert(
            session, user.id, "ETH-USD",
            price_level=3000.0, direction="below",
        )

        with patch(
            "backend.services.price_alert_service.check_single_price",
            new_callable=AsyncMock,
            return_value=3000.0,
        ):
            outcomes = await check_price_alerts(session)

        assert len(outcomes) == 1
        assert outcomes[0]["status"] == "triggered"

    async def test_check_sends_notification(self, session, user):
        """Triggered alert sends notification via user's enabled channels."""
        # Create an alert channel for the user
        ch = AlertChannel(
            user_id=user.id,
            channel_type="telegram",
            config=json.dumps({"chat_id": "12345"}),
            enabled=1,
        )
        session.add(ch)
        await session.flush()

        a = await create_price_alert(
            session, user.id, "BTC-USD",
            price_level=50000.0, direction="above",
        )

        with (
            patch(
                "backend.services.price_alert_service.check_single_price",
                new_callable=AsyncMock,
                return_value=55000.0,
            ),
            patch(
                "backend.services.price_alert_service.send_alert",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_send,
        ):
            outcomes = await check_price_alerts(session)

        assert len(outcomes) == 1
        assert outcomes[0]["status"] == "triggered"
        assert "telegram" in outcomes[0]["channels_sent"]
        mock_send.assert_awaited_once()


# ── Message formatting tests ──────────────────────────────────────────────


class TestPriceAlertMessaging:
    """Tests for price alert message formatters."""

    def test_format_telegram_message_includes_all_fields(self):
        """Telegram message includes all alert details."""
        from backend.models import PriceAlert

        alert = PriceAlert(
            id=1, user_id=1, symbol="BTC-USD", alert_type="price",
            direction="above", price_level=70000.0, message="Moon shot!",
        )
        msg = _format_price_alert_message(alert, 71000.0, "above", "↗")
        assert "BTC-USD" in msg
        assert "70000.0" in msg
        assert "71000.0" in msg
        assert "ABOVE" in msg
        assert "Moon shot!" in msg

    def test_format_telegram_minimal(self):
        """Telegram message works with minimal alert (no message)."""
        from backend.models import PriceAlert

        alert = PriceAlert(
            id=2, user_id=1, symbol="ETH-USD", alert_type="target",
            direction="below", price_level=3000.0, message=None,
        )
        msg = _format_price_alert_message(alert, 2900.0, "below", "↘")
        assert "ETH-USD" in msg
        assert "3000.0" in msg
        assert "BELOW" in msg
        assert "Price Alert" in msg

    def test_discord_embed_includes_all_fields(self):
        """Discord embed has the right shape and content."""
        from backend.models import PriceAlert

        alert = PriceAlert(
            id=1, user_id=1, symbol="BTC-USD", alert_type="price",
            direction="above", price_level=70000.0, message="Test note",
        )
        embed = _build_price_alert_embed(alert, 71000.0, "above", "↗")
        assert embed["title"] == "🔔 Price Alert: BTC-USD"
        assert embed["color"] == 0x00FF00  # GREEN for above
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert "BTC-USD" in fields["🏷️ Symbol"]
        assert "70000.0" == fields["📊 Level"]
        assert "71000.0" == fields["💵 Current Price"]
        assert "ABOVE" == fields["📐 Direction"]
        assert "Test note" == fields["💬 Note"]

    def test_discord_embed_below_red(self):
        """Direction='below' uses RED embed color."""
        from backend.models import PriceAlert

        alert = PriceAlert(
            id=2, user_id=1, symbol="ETH-USD", alert_type="stop",
            direction="below", price_level=2500.0, message=None,
        )
        embed = _build_price_alert_embed(alert, 2400.0, "below", "↘")
        assert embed["color"] == 0xFF0000  # RED for below
        assert "BELOW" in embed["fields"][3]["value"]

    def test_discord_embed_no_message(self):
        """Discord embed omits Note field when no message."""
        from backend.models import PriceAlert

        alert = PriceAlert(
            id=3, user_id=1, symbol="SOL-USD", alert_type="price",
            direction="above", price_level=150.0, message=None,
        )
        embed = _build_price_alert_embed(alert, 160.0, "above", "↗")
        field_names = [f["name"] for f in embed["fields"]]
        assert "💬 Note" not in field_names


# ── API integration tests ──────────────────────────────────────────────────


class TestPriceAlertAPI:
    """Integration tests for the price alert HTTP endpoints."""

    async def test_create_via_api(self, app, tmp_db_path):
        """POST /api/v1/alerts/price creates a price alert."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": 70000.0,
                    "direction": "above",
                    "message": "Moon shot!",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "BTC-USD"
        assert data["price_level"] == 70000.0
        assert data["direction"] == "above"
        assert data["message"] == "Moon shot!"
        assert data["status"] == "active"

    async def test_create_validates_symbol(self, app, tmp_db_path):
        """POST rejects empty symbol."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/alerts/price",
                json={"symbol": "", "price_level": 100.0, "direction": "above"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 422

    async def test_create_validates_direction(self, app, tmp_db_path):
        """POST rejects invalid direction."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": 70000.0,
                    "direction": "invalid",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 422

    async def test_create_validates_price_level_gt_zero(self, app, tmp_db_path):
        """POST rejects price_level <= 0."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/alerts/price",
                json={"symbol": "BTC-USD", "price_level": 0, "direction": "above"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 422

            response = await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": -10,
                    "direction": "above",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 422

    async def test_list_via_api(self, app, tmp_db_path):
        """GET /api/v1/alerts/price returns user's alerts."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create two alerts
            await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": 70000.0,
                    "direction": "above",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "ETH-USD",
                    "price_level": 3000.0,
                    "direction": "below",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

            response = await client.get(
                "/api/v1/alerts/price",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["alerts"]) == 2

    async def test_list_filter_by_status(self, app, tmp_db_path):
        """GET /api/v1/alerts/price?status=cancelled filters correctly."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": 70000.0,
                    "direction": "above",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            alert_id = resp.json()["id"]

            # Cancel it
            await client.put(
                f"/api/v1/alerts/price/{alert_id}",
                json={"status": "cancelled"},
                headers={"Authorization": f"Bearer {token}"},
            )

            # List active - should be 0
            resp_active = await client.get(
                "/api/v1/alerts/price?status=active",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp_active.json()["total"] == 0

            # List cancelled - should be 1
            resp_cancelled = await client.get(
                "/api/v1/alerts/price?status=cancelled",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp_cancelled.json()["total"] == 1

    async def test_get_via_api(self, app, tmp_db_path):
        """GET /api/v1/alerts/price/{id} returns a single alert."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": 70000.0,
                    "direction": "above",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            alert_id = resp.json()["id"]

            resp_get = await client.get(
                f"/api/v1/alerts/price/{alert_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp_get.status_code == 200
        assert resp_get.json()["id"] == alert_id
        assert resp_get.json()["symbol"] == "BTC-USD"

    async def test_get_via_api_not_found(self, app, tmp_db_path):
        """GET /api/v1/alerts/price/9999 returns 404."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/alerts/price/9999",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 404

    async def test_cancel_via_api(self, app, tmp_db_path):
        """PUT /api/v1/alerts/price/{id} with status=cancelled cancels the alert."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": 70000.0,
                    "direction": "above",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            alert_id = resp.json()["id"]

            resp_cancel = await client.put(
                f"/api/v1/alerts/price/{alert_id}",
                json={"status": "cancelled"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp_cancel.status_code == 200
        assert resp_cancel.json()["status"] == "cancelled"

    async def test_cancel_via_api_not_found(self, app, tmp_db_path):
        """PUT /api/v1/alerts/price/9999 returns 404."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/v1/alerts/price/9999",
                json={"status": "cancelled"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 404

    async def test_delete_via_api(self, app, tmp_db_path):
        """DELETE /api/v1/alerts/price/{id} deletes the alert."""
        from backend.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            _, token = await _create_api_user(session)
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": 70000.0,
                    "direction": "above",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            alert_id = resp.json()["id"]

            resp_del = await client.delete(
                f"/api/v1/alerts/price/{alert_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp_del.status_code == 204

            # Verify it's gone
            resp_get = await client.get(
                f"/api/v1/alerts/price/{alert_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp_get.status_code == 404

    async def test_unauthenticated_fails(self, tmp_db_path):
        """Requests without auth token return 401."""
        from backend import database

        database._DB_PATH = None
        database._engine = None
        database._session_factory = None
        set_db_path(tmp_db_path)

        engine = database.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        from backend.main import app as _app

        transport = ASGITransport(app=_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/alerts/price",
                json={
                    "symbol": "BTC-USD",
                    "price_level": 70000.0,
                    "direction": "above",
                },
            )
        assert response.status_code == 401
