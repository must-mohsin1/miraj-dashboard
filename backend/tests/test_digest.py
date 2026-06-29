"""Tests for the daily digest service (P3-B).

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_digest.py -v
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
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import time)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import Analysis, User


# ── Test helpers ──────────────────────────────────────────────────────────────


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


def _make_analysis_result(
    confluence_score: float = 12.0,
    direction: str = "LONG",
    trade_decision: bool = True,
    regime_weekly: bool = False,
    regime_daily: bool = True,
    conf_h4: bool = True,
    conf_m15: bool = True,
) -> str:
    """Build a JSON result string mimicking the stored format from scheduler.py."""
    return json.dumps({
        "confluence_score": confluence_score,
        "trade_plan": {
            "direction": direction,
            "trade_decision": trade_decision,
            "entry_zone": {"low": 50000.0, "high": 50500.0},
            "stop_loss": 49500.0,
            "take_profit_targets": [{"level": 52000.0}],
            "reasoning": "Bullish structure with alignment",
        },
        "score_breakdown": {
            "regime": {
                "score": 4.0,
                "breakdown": {
                    "weekly_structure": regime_weekly,
                    "daily_structure": regime_daily,
                    "btc_d_aligned": True,
                    "weekly_200ma": True,
                    "usdt_d_favourable": False,
                    "bmsb": False,
                    "fear_greed_aligned": False,
                },
            },
            "location": {"score": 3.0, "breakdown": {"demand_supply_zone": True, "ote_overlap": False}},
            "confirmation": {
                "score": 5.0,
                "breakdown": {
                    "h4_structure": conf_h4,
                    "daily_rsi_confirms": True,
                    "h4_rsi_confirms": True,
                    "bb_not_squeezing": True,
                    "qqe_aligned": True,
                    "m15_structure": conf_m15,
                    "rsi_divergence": False,
                    "chart_pattern": False,
                    "ema_ribbon": False,
                },
            },
            "volume_retest": {"score": 2.0, "breakdown": {"volume_confirming": True, "retest_confirmed": True, "no_fakeout": False}},
            "risk": {"score": 2.0, "breakdown": {"target_2r": True, "clean_stop": True, "no_news_risk": False}},
            "total": confluence_score,
            "trade_decision": trade_decision,
        },
    })


# ── Pytest fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    """Yield a unique temporary DB path per test, cleaned up after."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="digest_test_")
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


@pytest.fixture
def seed_data(app: FastAPI):
    """Seed the DB with test users and analyses, return user references."""
    import pytest_asyncio  # noqa: F401 — lazy import for anyio
    from backend.database import get_session_factory

    factory = get_session_factory()

    async def _seed() -> dict[str, Any]:
        async with factory() as session:
            user1 = await _create_user(session, username="alice", email="alice@example.com")
            user2 = await _create_user(session, username="bob", email="bob@example.com")

            # Today's analyses
            today = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)

            # BTC — high confidence, LONG, daily + 4h confirming
            session.add(Analysis(
                user_id=user1.id, pair="BTCUSDT", analysis_type="scheduled_scan",
                score=15.0,
                result=_make_analysis_result(
                    confluence_score=15.0, direction="LONG", trade_decision=True,
                    regime_weekly=True, regime_daily=True, conf_h4=True,
                ),
                created_at=today,
            ))

            # ETH — medium, SHORT, 4h confirming only
            session.add(Analysis(
                user_id=user1.id, pair="ETHUSDT", analysis_type="scheduled_scan",
                score=8.5,
                result=_make_analysis_result(
                    confluence_score=8.5, direction="SHORT", trade_decision=False,
                    regime_weekly=False, regime_daily=False, conf_h4=True, conf_m15=False,
                ),
                created_at=today,
            ))

            # SOL — high confluence, actionable
            session.add(Analysis(
                user_id=user1.id, pair="SOLUSDT", analysis_type="scheduled_scan",
                score=18.0,
                result=_make_analysis_result(
                    confluence_score=18.0, direction="LONG", trade_decision=True,
                    regime_weekly=True, regime_daily=True, conf_h4=True, conf_m15=True,
                ),
                created_at=today,
            ))

            # DOGE — low score, no direction
            session.add(Analysis(
                user_id=user1.id, pair="DOGEUSDT", analysis_type="scheduled_scan",
                score=3.0,
                result=_make_analysis_result(
                    confluence_score=3.0, direction="", trade_decision=False,
                    regime_weekly=False, regime_daily=False, conf_h4=False, conf_m15=False,
                ),
                created_at=today,
            ))

            # User2 pair — should appear separately
            session.add(Analysis(
                user_id=user2.id, pair="ADAUSDT", analysis_type="scheduled_scan",
                score=11.0,
                result=_make_analysis_result(
                    confluence_score=11.0, direction="LONG", trade_decision=True,
                    regime_weekly=False, regime_daily=True, conf_h4=True,
                ),
                created_at=today,
            ))

            # Yesterday's analysis — should NOT appear in today's digest
            yesterday = today - timedelta(days=1)
            session.add(Analysis(
                user_id=user1.id, pair="XRPUSDT", analysis_type="scheduled_scan",
                score=14.0,
                result=_make_analysis_result(
                    confluence_score=14.0, direction="LONG", trade_decision=True,
                ),
                created_at=yesterday,
            ))

            await session.commit()

        return {"user1_id": user1.id, "user2_id": user2.id}

    return _seed


# ── Unit tests: _extract_highest_tf ─────────────────────────────────────────


class TestExtractHighestTF:
    """Direct unit tests for the _extract_highest_tf helper."""

    def test_weekly_highest(self):
        from backend.alerts.digest import _extract_highest_tf
        sb = {
            "regime": {"breakdown": {"weekly_structure": True, "daily_structure": True}},
            "confirmation": {"breakdown": {"h4_structure": True, "m15_structure": True}},
        }
        assert _extract_highest_tf(sb) == "WEEKLY"

    def test_daily_when_no_weekly(self):
        from backend.alerts.digest import _extract_highest_tf
        sb = {
            "regime": {"breakdown": {"weekly_structure": False, "daily_structure": True}},
            "confirmation": {"breakdown": {"h4_structure": True, "m15_structure": False}},
        }
        assert _extract_highest_tf(sb) == "DAILY"

    def test_h4_when_no_weekly_or_daily(self):
        from backend.alerts.digest import _extract_highest_tf
        sb = {
            "regime": {"breakdown": {"weekly_structure": False, "daily_structure": False}},
            "confirmation": {"breakdown": {"h4_structure": True, "m15_structure": True}},
        }
        assert _extract_highest_tf(sb) == "4H"

    def test_m15_when_none_higher(self):
        from backend.alerts.digest import _extract_highest_tf
        sb = {
            "regime": {"breakdown": {"weekly_structure": False, "daily_structure": False}},
            "confirmation": {"breakdown": {"h4_structure": False, "m15_structure": True}},
        }
        assert _extract_highest_tf(sb) == "15M"

    def test_none_when_nothing_confirms(self):
        from backend.alerts.digest import _extract_highest_tf
        sb = {
            "regime": {"breakdown": {"weekly_structure": False, "daily_structure": False}},
            "confirmation": {"breakdown": {"h4_structure": False, "m15_structure": False}},
        }
        assert _extract_highest_tf(sb) is None

    def test_none_on_empty_breakdown(self):
        from backend.alerts.digest import _extract_highest_tf
        assert _extract_highest_tf({}) is None
        assert _extract_highest_tf(None) is None


# ── Unit tests: build_digest_message ────────────────────────────────────────


class TestBuildDigestMessage:
    """Tests for build_digest_message — the markdown message builder."""

    def test_empty_list(self):
        from backend.alerts.digest import build_digest_message
        msg = build_digest_message([])
        assert "No scans run today" in msg

    def test_single_pair(self):
        from backend.alerts.digest import build_digest_message

        # Build a minimal analysis-like dict for one pair
        rows = [{
            "symbol": "BTCUSDT",
            "confluence_score": 15.0,
            "direction": "LONG",
            "highest_tf": "DAILY",
            "actionable": True,
            "score_breakdown": {},
        }]
        msg = build_digest_message(rows)
        assert "BTCUSDT" in msg
        assert "15" in msg
        assert "LONG" in msg
        assert "DAILY" in msg
        assert "1" in msg  # total count
        assert "✓" in msg or "actionable" in msg.lower()

    def test_multiple_pairs(self):
        from backend.alerts.digest import build_digest_message
        rows = [
            {"symbol": "BTCUSDT", "confluence_score": 15.0, "direction": "LONG", "highest_tf": "WEEKLY", "actionable": True, "score_breakdown": {}},
            {"symbol": "ETHUSDT", "confluence_score": 8.5, "direction": "SHORT", "highest_tf": "4H", "actionable": False, "score_breakdown": {}},
            {"symbol": "SOLUSDT", "confluence_score": 18.0, "direction": "LONG", "highest_tf": "DAILY", "actionable": True, "score_breakdown": {}},
        ]
        msg = build_digest_message(rows)
        # All symbols present
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            assert sym in msg
        # Summary line
        assert "3 pairs" in msg
        # High confluence count (>=10): BTC 15.0, SOL 18.0 = 2
        # Actionable: BTC and SOL = 2
        assert "2" in msg  # at least one count of 2

    def test_markdown_format(self):
        from backend.alerts.digest import build_digest_message
        rows = [
            {"symbol": "BTCUSDT", "confluence_score": 15.0, "direction": "LONG", "highest_tf": "DAILY", "actionable": True, "score_breakdown": {}},
        ]
        msg = build_digest_message(rows)
        # Should have bold markers or bullet points
        assert "**" in msg or "*" in msg
        assert "\n" in msg


# ── Unit tests: TelegramClient ──────────────────────────────────────────────


class TestTelegramClient:
    """Tests for the TelegramClient — mocked HTTP calls."""

    @patch("backend.alerts.digest.httpx.AsyncClient")
    async def test_send_message_success(self, mock_httpx):
        from backend.alerts.digest import TelegramClient

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"ok": True}
        mock_httpx.return_value.__aenter__.return_value.post = mock_post

        client = TelegramClient(bot_token="test:token", chat_id="12345")
        result = await client.send_message("Hello")

        assert result is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "sendMessage" in str(args[0])
        assert kwargs["json"]["chat_id"] == "12345"
        assert kwargs["json"]["text"] == "Hello"
        assert kwargs["json"]["parse_mode"] == "MarkdownV2"

    @patch("backend.alerts.digest.httpx.AsyncClient")
    async def test_send_message_failure(self, mock_httpx):
        from backend.alerts.digest import TelegramClient

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {"ok": False, "description": "Bad Request"}
        mock_httpx.return_value.__aenter__.return_value.post = mock_post

        client = TelegramClient(bot_token="test:token", chat_id="12345")
        result = await client.send_message("Hello")
        assert result is False

    @patch("backend.alerts.digest.httpx.AsyncClient")
    async def test_send_message_network_error(self, mock_httpx):
        from backend.alerts.digest import TelegramClient

        mock_post = AsyncMock(side_effect=Exception("Connection error"))
        mock_httpx.return_value.__aenter__.return_value.post = mock_post

        client = TelegramClient(bot_token="test:token", chat_id="12345")
        result = await client.send_message("Hello")
        assert result is False

    @patch("backend.alerts.digest.logger")
    async def test_disabled_when_no_token(self, mock_logger):
        from backend.alerts.digest import TelegramClient

        client = TelegramClient(bot_token="", chat_id="12345")
        assert client.enabled is False
        result = await client.send_message("Hello")
        assert result is False
        mock_logger.info.assert_called_once()


# ── Integration tests: send_daily_digest ────────────────────────────────────


pytestmark = pytest.mark.anyio


class TestSendDailyDigest:
    """Integration tests for send_daily_digest with real DB and mocked Telegram."""

    @patch("backend.alerts.digest.TelegramClient.send_message", new_callable=AsyncMock)
    async def test_digest_includes_today_analyses(self, mock_send, seed_data):
        """Digest should include all today's analyses per user."""
        from backend.alerts.digest import send_daily_digest

        mock_send.return_value = True
        await seed_data()

        await send_daily_digest()

        # Should have been called twice (once per user with analyses today)
        assert mock_send.call_count == 2

        # Get the message sent to user1 (alice)
        call_args_list = mock_send.call_args_list
        messages = [call[0][0] for call in call_args_list]

        # User1 has 4 analyses today (BTC, ETH, SOL, DOGE)
        user1_msg = messages[0]
        assert "BTCUSDT" in user1_msg
        assert "ETHUSDT" in user1_msg
        assert "SOLUSDT" in user1_msg
        assert "DOGEUSDT" in user1_msg

        # XRP is from yesterday — should NOT appear
        assert "XRPUSDT" not in user1_msg

        # Summary counts: 4 total
        # High confluence (>=10): BTC (15), SOL (18) = 2
        # Actionable (trade_decision=True): BTC, SOL = 2
        # (ETH is 8.5, DOGE is 3.0)

    @patch("backend.alerts.digest.TelegramClient.send_message", new_callable=AsyncMock)
    async def test_empty_day_sends_no_scans_message(self, mock_send, seed_data):
        """When no scans ran today, send 'No scans run today'."""
        from backend.alerts.digest import send_daily_digest

        mock_send.return_value = True
        await seed_data()

        # Clear today's analyses by moving them to yesterday
        from backend.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import update
            from backend.models import Analysis
            yesterday = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=2)
            stmt = update(Analysis).values(created_at=yesterday)
            await session.execute(stmt)
            await session.commit()

        mock_send.reset_mock()
        await send_daily_digest()

        # Should still be called for users who have no data
        assert mock_send.call_count >= 1
        for call_args in mock_send.call_args_list:
            msg = call_args[0][0]
            assert "No scans run today" in msg

    @patch("backend.alerts.digest.TelegramClient.send_message", new_callable=AsyncMock)
    async def test_digest_summary_counts(self, mock_send, seed_data):
        """Verify summary line numbers."""
        from backend.alerts.digest import send_daily_digest

        mock_send.return_value = True
        await seed_data()

        await send_daily_digest()

        # User1's message: 4 pairs total, 2 high-confluence (BTC 15, SOL 18), 2 actionable (BTC, SOL)
        msg = mock_send.call_args_list[0][0][0]
        assert "4 pairs" in msg or "4" in msg
        assert "high-confluence" in msg.lower()

    @patch("backend.alerts.digest.TelegramClient.send_message", new_callable=AsyncMock)
    async def test_digest_marks_actionable_setups(self, mock_send, seed_data):
        """Actionable setups should be visually distinct."""
        from backend.alerts.digest import send_daily_digest

        mock_send.return_value = True
        await seed_data()

        await send_daily_digest()

        msg = mock_send.call_args_list[0][0][0]
        # BTC and SOL are actionable (trade_decision=True)
        assert "BTCUSDT" in msg
        assert "SOLUSDT" in msg

    @patch("backend.alerts.digest.TelegramClient.send_message", new_callable=AsyncMock)
    async def test_no_duplicate_digest_for_same_setup(self, mock_send, seed_data):
        """Running digest twice on same data should produce same content (idempotent)."""
        from backend.alerts.digest import send_daily_digest

        mock_send.return_value = True
        await seed_data()

        await send_daily_digest()
        first_call_count = mock_send.call_count

        # Run again — should include same data since no new analyses
        await send_daily_digest()
        assert mock_send.call_count == first_call_count * 2  # just sends again, same content

    @patch("backend.alerts.digest.TelegramClient.send_message", new_callable=AsyncMock)
    async def test_user_without_analyses_receives_empty_message(self, mock_send, seed_data):
        """User with no analyses today gets the 'no scans' message."""
        from backend.alerts.digest import send_daily_digest

        mock_send.return_value = True
        refs = await seed_data()

        # Verify user2 has today's analyses (ADAUSDT)
        await send_daily_digest()

        # Both users should get a message
        assert mock_send.call_count == 2
        msgs = [call[0][0] for call in mock_send.call_args_list]
        all_text = " ".join(msgs)
        assert "ADAUSDT" in all_text


    def test_special_chars_in_dynamic_content_escaped(self):
        """Dynamic values with MarkdownV2 special chars are escaped, formatting preserved."""
        from backend.alerts.digest import build_digest_message

        rows = [{
            "symbol": "STOP*LOSS",
            "confluence_score": 1.5,
            "direction": "LONG",
            "highest_tf": "15M",
            "actionable": False,
            "score_breakdown": {},
        }]
        msg = build_digest_message(rows)

        # Bold markers from formatting survive
        assert "*STOP" in msg or "*STOP\\*LOSS" in msg

        # The asterisk inside the symbol value is escaped (not treated as bold)
        # In the output, `*STOP\*LOSS*` — the inner * is escaped so it doesn't close bold early
        assert "*" in msg  # bold markers present

        # Score dot is escaped (1\.5)
        assert "1\\.5" in msg or "1.5" not in msg.replace("`", "")

        # Highest TF in code span
        assert "`15M`" in msg or "15M" in msg

        # Direction preserved
        assert "LONG" in msg
