"""Integration coverage for the authenticated Decision Desk snapshot route."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend.auth import create_access_token, hash_password
from backend.database import Base, get_engine, get_session_factory, set_db_path
from backend.models import (
    AlertChannel,
    ExchangeKey,
    PortfolioSnapshot,
    RealtimeNotification,
    RealtimeSignal,
    User,
    WatchlistPair,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def app() -> FastAPI:
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="decision_desk_test_")
    os.close(fd)

    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(db_path)

    from backend.main import app as main_app

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield main_app

    await get_engine().dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client


@pytest.mark.anyio
async def test_now_returns_authenticated_user_watchlist_scope_and_persisted_signal_lifecycle(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from backend.routes import decision_desk

    async def fake_catalogue() -> set[str]:
        return {"BTC_USDT"}

    monkeypatch.setattr(decision_desk, "fetch_mexc_contract_catalogue", fake_catalogue)

    observed_at = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    factory = get_session_factory()
    async with factory() as session:
        user = User(username="desk-user", email="desk@example.com", hashed_password=hash_password("testpass123"))
        other_user = User(username="other-user", email="other@example.com", hashed_password=hash_password("testpass123"))
        session.add_all([user, other_user])
        await session.flush()
        session.add_all(
            [
                WatchlistPair(user_id=user.id, pair="BTC-USDT", sort_order=0),
                WatchlistPair(user_id=user.id, pair="ETH-USD", sort_order=1),
                RealtimeSignal(
                    user_id=user.id,
                    pair="BTCUSDT",
                    direction="LONG",
                    state="ACTIONABLE",
                    dedup_key="BTCUSDT:LONG:ACTIONABLE:1",
                    transition_count=1,
                    missing_gates="[]",
                    created_at=observed_at,
                    updated_at=observed_at,
                ),
                RealtimeSignal(
                    user_id=other_user.id,
                    pair="SOLUSDT",
                    direction="SHORT",
                    state="STALE",
                    dedup_key="SOLUSDT:SHORT:STALE:1",
                    transition_count=1,
                    missing_gates='["freshness"]',
                    created_at=observed_at,
                    updated_at=observed_at,
                ),
            ]
        )
        await session.commit()

    token = create_access_token(data={"sub": str(user.id)})
    response = await client.get("/api/v1/decision-desk/now", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated_at"]
    assert payload["watchlist"] == [
        {"pair": "BTC-USDT", "market_scope": "mexc_realtime", "mexc_symbol": "BTCUSDT"},
        {"pair": "ETH-USD", "market_scope": "research_only", "mexc_symbol": None},
    ]
    assert payload["signals"] == [
        {
            "pair": "BTCUSDT",
            "direction": "LONG",
            "state": "ACTIONABLE",
            "missing_gates": [],
            "created_at": "2026-07-17T12:00:00",
            "updated_at": "2026-07-17T12:00:00",
        }
    ]
    assert payload["notification_channels"] == []
    assert payload["notification_outbox"] == []
    assert payload["account_reconciliation"] == []


@pytest.mark.anyio
async def test_now_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/decision-desk/now")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_now_returns_only_safe_current_user_outbox_evidence_and_cached_reconciliation_freshness(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from backend.routes import decision_desk

    async def fake_catalogue() -> set[str]:
        return set()

    monkeypatch.setattr(decision_desk, "fetch_mexc_contract_catalogue", fake_catalogue)
    observed_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    factory = get_session_factory()
    async with factory() as session:
        user = User(username="evidence-user", email="evidence@example.com", hashed_password=hash_password("testpass123"))
        other_user = User(username="other-evidence-user", email="other-evidence@example.com", hashed_password=hash_password("testpass123"))
        session.add_all([user, other_user])
        await session.flush()
        telegram = AlertChannel(
            user_id=user.id,
            channel_type="telegram",
            config='{"chat_id":"private-chat-id"}',
            enabled=1,
            created_at=observed_at,
            updated_at=observed_at,
        )
        discord = AlertChannel(
            user_id=user.id,
            channel_type="discord",
            config='{"webhook_url":"https://discord.example/private-webhook"}',
            enabled=0,
            created_at=observed_at,
            updated_at=observed_at,
        )
        other_channel = AlertChannel(user_id=other_user.id, channel_type="telegram", config='{"chat_id":"other"}', enabled=1)
        signal = RealtimeSignal(
            user_id=user.id,
            pair="BTCUSDT",
            direction="LONG",
            state="ACTIONABLE",
            dedup_key="BTCUSDT:LONG:ACTIONABLE:1",
            transition_count=1,
            created_at=observed_at,
            updated_at=observed_at,
        )
        other_signal = RealtimeSignal(
            user_id=other_user.id,
            pair="SOLUSDT",
            direction="SHORT",
            state="STALE",
            dedup_key="SOLUSDT:SHORT:STALE:1",
            transition_count=1,
        )
        session.add_all([telegram, discord, other_channel, signal, other_signal])
        await session.flush()
        session.add_all(
            [
                RealtimeNotification(signal_id=signal.id, channel_id=telegram.id, dedup_key="pending", status="pending", attempts=1, created_at=observed_at),
                RealtimeNotification(signal_id=signal.id, channel_id=telegram.id, dedup_key="sent", status="sent", attempts=1, created_at=observed_at, sent_at=observed_at),
                RealtimeNotification(signal_id=signal.id, channel_id=telegram.id, dedup_key="failed", status="failed", attempts=2, created_at=observed_at, last_error="POST https://discord.example/private-webhook?token=private-token failed"),
                RealtimeNotification(signal_id=signal.id, channel_id=discord.id, dedup_key="cancelled", status="cancelled", attempts=1, created_at=observed_at),
                RealtimeNotification(signal_id=other_signal.id, channel_id=other_channel.id, dedup_key="other", status="sent", attempts=1, created_at=observed_at, sent_at=observed_at),
                PortfolioSnapshot(user_id=user.id, exchange="mexc", total_balance_usd=None, total_pnl_usd=4.0, open_positions=1, timestamp=observed_at),
                PortfolioSnapshot(user_id=user.id, exchange="kraken", total_balance_usd=None, total_pnl_usd=0.0, open_positions=0, timestamp=observed_at - timedelta(minutes=6)),
                ExchangeKey(user_id=user.id, exchange="binance", api_key_encrypted=b"ciphertext", api_secret_encrypted=b"ciphertext"),
            ]
        )
        await session.commit()

    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls) -> datetime:
            return observed_at

    monkeypatch.setattr(decision_desk, "datetime", FrozenDateTime)
    token = create_access_token(data={"sub": str(user.id)})
    response = await client.get("/api/v1/decision-desk/now", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["notification_channels"] == [
        {"channel_type": "telegram", "enabled": True, "configured": True, "updated_at": "2026-07-20T12:00:00"},
        {"channel_type": "discord", "enabled": False, "configured": True, "updated_at": "2026-07-20T12:00:00"},
    ]
    assert [(item["status"], item["pair"], item["channel_type"]) for item in payload["notification_outbox"]] == [
        ("cancelled", "BTCUSDT", "discord"),
        ("failed", "BTCUSDT", "telegram"),
        ("sent", "BTCUSDT", "telegram"),
        ("pending", "BTCUSDT", "telegram"),
    ]
    failed = next(item for item in payload["notification_outbox"] if item["status"] == "failed")
    assert failed["error"] == "POST [redacted-url] failed"
    assert failed["sent_at"] is None
    assert "private" not in response.text
    assert "ciphertext" not in response.text
    assert payload["account_reconciliation"] == [
        {"exchange": "binance", "freshness": "unavailable", "last_reconciled_at": None, "positions": []},
        {"exchange": "kraken", "freshness": "stale", "last_reconciled_at": "2026-07-20T11:54:00", "positions": []},
        {"exchange": "mexc", "freshness": "fresh", "last_reconciled_at": "2026-07-20T12:00:00", "positions": []},
    ]
