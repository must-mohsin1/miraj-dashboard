"""Retry semantics for committed real-time notification outbox rows."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import AlertChannel, RealtimeNotification, RealtimeSignal, User
from backend.realtime.worker import dispatch_pending_notifications


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
