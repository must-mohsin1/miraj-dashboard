"""Retry semantics for committed real-time notification outbox rows."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import AlertChannel, RealtimeNotification, RealtimeSignal, User
from backend.realtime.lifecycle import SignalEvaluation, SignalState
from backend.realtime.store import enqueue_transition_notifications
from backend.realtime.worker import _format_notification, dispatch_pending_notifications


def test_failed_pending_notification_remains_pending_with_incremented_attempts(monkeypatch):
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(User(id=21, username="retry", email="retry@example.com", hashed_password="x"))
            channel = AlertChannel(user_id=21, channel_type="telegram", config='{"chat_id":"1"}', enabled=1)
            session.add(channel)
            signal = RealtimeSignal(user_id=21, pair="SOLUSDT", direction="LONG", state="STALE", dedup_key="SOLUSDT:LONG:STALE")
            session.add(signal)
            await session.flush()
            session.add(RealtimeNotification(signal_id=signal.id, channel_id=channel.id, dedup_key=signal.dedup_key))
            await session.commit()

        async def failed_send(*_args, **_kwargs):
            return False

        monkeypatch.setattr("backend.alerts.telegram.send_alert", failed_send)
        await dispatch_pending_notifications(factory)
        async with factory() as session:
            row = (await session.execute(select(RealtimeNotification))).scalar_one()
            assert row.status == "pending"
            assert row.attempts == 1
            assert row.next_attempt_at is not None
        await engine.dispose()

    asyncio.run(scenario())


def test_stale_transition_is_persisted_but_not_enqueued_for_delivery():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(User(id=22, username="stale", email="stale@example.com", hashed_password="x"))
            session.add(AlertChannel(user_id=22, channel_type="discord", config="{}", enabled=1))
            signal = RealtimeSignal(
                user_id=22, pair="DOGEUSDT", direction="SHORT", state="STALE", dedup_key="DOGEUSDT:SHORT:STALE:1"
            )
            session.add(signal)
            await session.flush()
            evaluation = SignalEvaluation(SignalState.STALE, False, "DOGEUSDT:SHORT:STALE", ("fresh market data",))
            await enqueue_transition_notifications(session, signal, evaluation)
            assert (await session.execute(select(RealtimeNotification))).scalars().all() == []
        await engine.dispose()

    asyncio.run(scenario())


def test_actionable_message_includes_confirmation_and_manual_risk_review():
    signal = RealtimeSignal(
        pair="BTCUSDT",
        direction="LONG",
        state="ACTIONABLE",
        dedup_key="BTCUSDT:LONG:ACTIONABLE:1",
        missing_gates="[]",
        analysis_json='{"entry": 100.0, "invalidation": 95.0, "target_one": 110.0, "risk_reward": 2.0}',
    )
    text = _format_notification(signal)
    assert "Closed-candle review:" in text
    assert "higher-timeframe alignment" in text
    assert "Setup levels: entry 100 | invalidation 95 | target 1 110 | R:R 2.00" in text
    assert "validate current price and account exposure" in text
    assert "no order has been placed" in text
