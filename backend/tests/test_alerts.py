"""Tests for the Alert service (P3-A).

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_alerts.py -v

Tests cover:
- Telegram message formatting
- Discord embed building
- Alert manager: threshold filtering, dedup (cooldown), channel routing, history logging
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import time)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.alerts.discord import build_embed, send_webhook
from backend.alerts.manager import (
    DEFAULT_COOLDOWN_HOURS,
    DEFAULT_THRESHOLD,
    process_scan_results,
)
from backend.alerts.telegram import format_alert_message, send_alert
from backend.database import Base, get_session, set_db_path
from backend.models import AlertChannel, AlertHistory, PairSetting, User


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


pytestmark = pytest.mark.anyio


@pytest.fixture
def tmp_db_path() -> str:
    """Yield a unique temporary DB path per test, cleaned up after."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="alert_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def session(tmp_db_path: str):
    """Yield an async session backed by a fresh in-memory DB with all tables."""
    from backend import database

    # Reset singletons
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None

    set_db_path(tmp_db_path)

    # Create tables
    from backend.database import get_engine

    engine = get_engine()
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
        username="alertuser",
        email="alert@test.com",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


# ── Telegram format tests ────────────────────────────────────────────────────


class TestTelegramFormat:
    """Verify format_alert_message output matches spec criterion A-01."""

    def test_full_message(self):
        msg = format_alert_message(
            symbol="BTC-USD",
            score=85.5,
            direction="LONG",
            entry=65000.0,
            stop_loss=64000.0,
            target=68000.0,
            rationale="Strong bullish confluence",
        )
        assert "BTC-USD" in msg
        assert "85.5" in msg
        assert "LONG" in msg
        assert "65000.0" in msg
        assert "64000.0" in msg
        assert "68000.0" in msg
        assert "Strong bullish confluence" in msg

    def test_minimal_message(self):
        """Should still produce a valid message with only symbol and score."""
        msg = format_alert_message(symbol="ETH-USD", score=70.0, direction="SHORT")
        assert "ETH-USD" in msg
        assert "70.0" in msg
        assert "SHORT" in msg

    def test_emojis_present(self):
        """Check that key emoji markers are in the output."""
        msg = format_alert_message(symbol="SOL-USD", score=90.0, direction="LONG")
        # Feather / flag
        assert "\U0001f3f7\ufe0f" in msg
        # Star
        assert "\u2b50" in msg
        # Chart
        assert "\U0001f4ca" in msg


# ── Discord embed tests ──────────────────────────────────────────────────────


class TestDiscordEmbed:
    """Verify build_embed output shape and content."""

    def test_full_embed(self):
        embed = build_embed(
            symbol="BTC-USD",
            score=85.5,
            direction="LONG",
            entry=65000.0,
            stop_loss=64000.0,
            target=68000.0,
            rationale="Test rationale",
        )
        assert embed["title"] == "Trade Alert: BTC-USD"
        assert embed["color"] == 0x00FF00  # GREEN for LONG
        assert "timestamp" in embed
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert fields["\U0001f3f7\ufe0f Symbol"] == "BTC-USD"
        assert fields["\u2b50 Score"] == "85.5/100"
        assert fields["\U0001f4ca Direction"] == "LONG"
        assert fields["\U0001f4c5 Entry"] == "65000.0"
        assert fields["\U0001f6ab Stop Loss"] == "64000.0"
        assert fields["\U0001f3af Target"] == "68000.0"
        assert fields["\U0001f4ac Rationale"] == "Test rationale"

    def test_short_direction_red(self):
        """SHORT direction should produce RED embed color."""
        embed = build_embed(symbol="ETH-USD", score=30.0, direction="SHORT")
        assert embed["color"] == 0xFF0000  # RED

    def test_minimal_embed(self):
        """Only required fields present."""
        embed = build_embed(symbol="SOL-USD", score=70.0, direction="LONG")
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert "\U0001f4c5 Entry" not in fields
        assert "\U0001f6ab Stop Loss" not in fields
        assert "\U0001f3af Target" not in fields
        assert "\U0001f4ac Rationale" not in fields


# ── Alert manager tests ──────────────────────────────────────────────────────


class TestAlertManager:
    """Integration tests for process_scan_results with DB-backed stores."""

    # ── Helpers ─────────────────────────────────────────────────────────

    async def _add_channel(
        self, session, user_id: int, channel_type: str, config: dict[str, str]
    ) -> AlertChannel:
        ch = AlertChannel(
            user_id=user_id,
            channel_type=channel_type,
            config=json.dumps(config),
            enabled=1,
        )
        session.add(ch)
        await session.flush()
        await session.refresh(ch)
        return ch

    async def _set_threshold(
        self, session, user_id: int, pair: str, threshold: float
    ) -> None:
        ps = PairSetting(
            user_id=user_id,
            pair=pair,
            settings=json.dumps({"alert_threshold": threshold}),
        )
        session.add(ps)
        await session.flush()

    def _scan_result(self, symbol: str, score: float, direction: str = "LONG") -> dict[str, Any]:
        return {
            "symbol": symbol,
            "confluence_score": score,
            "overall_score": score,
            "trade_plan": {
                "trade_decision": True,
                "direction": direction,
                "entry": 100.0,
                "stop_loss": 95.0,
                "target_1": 110.0,
                "reasoning": "Bullish setup",
            },
            "score_breakdown": {"total": score},
            "stale": False,
            "cached_at": None,
        }

    # ── Threshold filtering ────────────────────────────────────────────

    async def test_below_threshold_no_alert(self, session, user):
        """Score below threshold should produce no alert (no send calls)."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})
        await self._set_threshold(session, user.id, "BTC-USD", 70.0)

        results_by_user = {user.id: [self._scan_result("BTC-USD", 50.0)]}

        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)

        mock_send.assert_not_called()
        assert outcomes == []

    async def test_above_threshold_sends_alert(self, session, user):
        """Score above threshold should trigger a send."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})
        await self._set_threshold(session, user.id, "BTC-USD", 50.0)

        results_by_user = {user.id: [self._scan_result("BTC-USD", 75.0)]}

        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)

        mock_send.assert_awaited_once()
        assert len(outcomes) == 1
        assert outcomes[0]["status"] == "sent"
        assert outcomes[0]["pair"] == "BTC-USD"
        assert outcomes[0]["channels_sent"] == ["telegram"]

    async def test_default_threshold_applied(self, session, user):
        """With no explicit threshold, DEFAULT_THRESHOLD (60) is used."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})

        # Score 55 — below default threshold of 60
        results_by_user = {user.id: [self._scan_result("BTC-USD", 55.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)
        mock_send.assert_not_called()
        assert outcomes == []

        # Score 65 — above default threshold of 60
        results_by_user = {user.id: [self._scan_result("ETH-USD", 65.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)
        mock_send.assert_awaited_once()
        assert len(outcomes) == 1
        assert outcomes[0]["status"] == "sent"

    # ── Dedup (cooldown) ─────────────────────────────────────────────

    async def test_dedup_within_cooldown(self, session, user):
        """Same symbol alerted twice within cooldown should skip second."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})

        # First alert — within cooldown
        cutoff = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_COOLDOWN_HOURS - 1)
        history = AlertHistory(
            user_id=user.id,
            pair="BTC-USD",
            channel="telegram",
            score=75.0,
            direction="LONG",
            message="Sent",
            status="sent",
            created_at=cutoff,
        )
        session.add(history)
        await session.flush()

        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)

        # Dedup should prevent sending
        mock_send.assert_not_called()
        assert outcomes == []

    async def test_dedup_after_cooldown_expired(self, session, user):
        """Same symbol alerted beyond cooldown should allow new alert."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})

        # Old alert (beyond cooldown)
        old_cutoff = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_COOLDOWN_HOURS + 1)
        history = AlertHistory(
            user_id=user.id,
            pair="BTC-USD",
            channel="telegram",
            score=75.0,
            direction="LONG",
            message="Sent",
            status="sent",
            created_at=old_cutoff,
        )
        session.add(history)
        await session.flush()

        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)

        mock_send.assert_awaited_once()
        assert len(outcomes) == 1
        assert outcomes[0]["status"] == "sent"

    # ── Channel routing ──────────────────────────────────────────────

    async def test_multiple_channels(self, session, user):
        """Alert should be sent to all enabled channels."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})
        await self._add_channel(session, user.id, "discord", {"webhook_url": "https://discord.com/api/webhooks/xxx"})

        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}

        with (
            patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as mock_tg,
            patch("backend.alerts.manager.send_webhook", new_callable=AsyncMock, return_value=True) as mock_dc,
        ):
            outcomes = await process_scan_results(session, results_by_user)

        mock_tg.assert_awaited_once()
        mock_dc.assert_awaited_once()
        assert len(outcomes) == 1
        assert outcomes[0]["channels_sent"] == ["telegram", "discord"]

    async def test_disabled_channel_skipped(self, session, user):
        """A disabled channel should not receive alerts."""
        ch = await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})
        ch.enabled = 0
        await session.flush()

        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)

        mock_send.assert_not_called()
        assert outcomes == []

    async def test_no_channels_no_alert(self, session, user):
        """User with no alert channels should not get alerts."""
        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)

        mock_send.assert_not_called()
        assert outcomes == []

    # ── Incomplete config warnings ──────────────────────────────

    async def test_telegram_missing_chat_id_logs_warning(self, session, user, caplog):
        """Telegram channel without chat_id should log a warning, not silently skip."""
        import logging

        caplog.set_level(logging.WARNING)
        await self._add_channel(session, user.id, "telegram", {})

        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as mock_send:
            await process_scan_results(session, results_by_user)

        mock_send.assert_not_called()
        assert "chat_id" in caplog.text or "missing" in caplog.text

    async def test_discord_missing_webhook_url_logs_warning(self, session, user, caplog):
        """Discord channel without webhook_url should log a warning, not silently skip."""
        import logging

        caplog.set_level(logging.WARNING)
        await self._add_channel(session, user.id, "discord", {})

        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}
        with patch("backend.alerts.manager.send_webhook", new_callable=AsyncMock) as mock_send:
            await process_scan_results(session, results_by_user)

        mock_send.assert_not_called()
        assert "webhook_url" in caplog.text or "missing" in caplog.text

    # ── History logging ──────────────────────────────────────────────

    async def test_alert_history_logged(self, session, user):
        """Successful sends should be logged to AlertHistory."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})

        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True):
            await process_scan_results(session, results_by_user)

        # Check history
        from sqlalchemy import select

        result = await session.execute(
            select(AlertHistory).where(AlertHistory.user_id == user.id)
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.pair == "BTC-USD"
        assert row.channel == "telegram"
        assert row.status == "sent"
        assert row.score == 80.0
        assert row.direction == "LONG"

    async def test_failed_send_logged_as_failed(self, session, user):
        """When send_alert returns False, history should log status='failed'."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})

        results_by_user = {user.id: [self._scan_result("BTC-USD", 80.0)]}
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=False):
            outcomes = await process_scan_results(session, results_by_user)

        assert len(outcomes) == 1
        assert outcomes[0]["status"] == "failed"

        from sqlalchemy import select

        result = await session.execute(
            select(AlertHistory).where(AlertHistory.user_id == user.id)
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "failed"

    # ── Silent on no qualifying pairs ────────────────────────────────

    async def test_silent_when_no_pair_qualifies(self, session, user):
        """No alert when no pair scores >= threshold (silent = correct)."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})
        await self._set_threshold(session, user.id, "BTC-USD", 90.0)

        results_by_user = {
            user.id: [
                self._scan_result("BTC-USD", 50.0),
                self._scan_result("ETH-USD", 30.0),
            ]
        }
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)

        mock_send.assert_not_called()
        assert outcomes == []

    # ── Dedup across multiple pairs ──────────────────────────────────

    async def test_dedup_only_applies_to_same_symbol(self, session, user):
        """Dedup for BTC-USD should not prevent alert for ETH-USD."""
        await self._add_channel(session, user.id, "telegram", {"chat_id": "12345"})

        # Recent alert for BTC-USD
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        session.add(AlertHistory(
            user_id=user.id, pair="BTC-USD", channel="telegram",
            score=70.0, direction="LONG", message="Sent", status="sent",
            created_at=recent,
        ))
        await session.flush()

        results_by_user = {
            user.id: [
                self._scan_result("BTC-USD", 80.0),
                self._scan_result("ETH-USD", 75.0),
            ]
        }
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as mock_send:
            outcomes = await process_scan_results(session, results_by_user)

        # Only ETH-USD should be sent
        assert mock_send.await_count == 1
        assert len(outcomes) == 1
        assert outcomes[0]["pair"] == "ETH-USD"


# ── Discord webhook send tests ──────────────────────────────────────────────


class TestDiscordSend:
    """Test send_webhook with mocked httpx."""

    # ── URL validation ──────────────────────────────────────────

    async def test_invalid_url_returns_false(self):
        """A non-Discord webhook URL should be rejected before making HTTP calls."""
        embed = build_embed(symbol="BTC-USD", score=80.0, direction="LONG")
        # No mock needed — validation happens before httpx is touched
        result = await send_webhook("https://evil.example.com/hook", embed)
        assert result is False

    async def test_valid_url_accepted(self):
        """A valid Discord webhook URL should proceed to HTTP (and be caught by mock)."""
        embed = build_embed(symbol="BTC-USD", score=80.0, direction="LONG")
        with patch("backend.alerts.discord.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_response = AsyncMock()
            mock_response.is_success = True
            mock_client.post.return_value = mock_response
            result = await send_webhook(
                "https://discord.com/api/webhooks/123/abc", embed
            )
        assert result is True

    async def test_success(self):
        embed = build_embed(symbol="BTC-USD", score=80.0, direction="LONG")

        with patch("backend.alerts.discord.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_response = AsyncMock()
            mock_response.is_success = True
            mock_client.post.return_value = mock_response

            result = await send_webhook("https://discord.com/api/webhooks/test", embed)

        assert result is True

    async def test_failure(self):
        embed = build_embed(symbol="BTC-USD", score=80.0, direction="LONG")

        with patch("backend.alerts.discord.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_response = AsyncMock()
            mock_response.is_success = False
            mock_response.status_code = 400
            mock_client.post.return_value = mock_response

            result = await send_webhook("https://discord.com/api/webhooks/test", embed)

        assert result is False

    async def test_timeout(self):
        embed = build_embed(symbol="BTC-USD", score=80.0, direction="LONG")

        with patch("backend.alerts.discord.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            from httpx import TimeoutException
            mock_client.post.side_effect = TimeoutException("Timeout")

            result = await send_webhook("https://discord.com/api/webhooks/test", embed)

        assert result is False
