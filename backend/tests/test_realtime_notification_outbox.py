"""Durable outbox behaviour for real-time lifecycle notifications."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import AlertChannel, RealtimeNotification, User
from backend.realtime.lifecycle import SignalEvaluation, SignalState
from backend.realtime.store import enqueue_transition_notifications, record_transition


def test_transition_queues_a_durable_pending_notification_before_delivery():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        evaluation = SignalEvaluation(SignalState.ACTIONABLE, True, "SOLUSDT:LONG:ACTIONABLE", ())
        async with factory() as session:
            session.add(User(id=17, username="outbox", email="outbox@example.com", hashed_password="x"))
            session.add(AlertChannel(user_id=17, channel_type="telegram", config='{"chat_id":"1"}', enabled=1))
            await session.commit()
            invalidated = SignalEvaluation(SignalState.INVALIDATED, False, "SOLUSDT:LONG:INVALIDATED", ())
            transition = await record_transition(session, 17, "SOLUSDT", "LONG", evaluation)
            await enqueue_transition_notifications(session, transition.signal, evaluation)
            transition = await record_transition(session, 17, "SOLUSDT", "LONG", invalidated)
            await enqueue_transition_notifications(session, transition.signal, invalidated)
            transition = await record_transition(session, 17, "SOLUSDT", "LONG", evaluation)
            await enqueue_transition_notifications(session, transition.signal, evaluation)
            await session.commit()
            rows = (await session.execute(select(RealtimeNotification))).scalars().all()
            assert len(rows) == 3
            assert all(row.status == "pending" for row in rows)
            assert {row.dedup_key for row in rows} == {
                "SOLUSDT:LONG:ACTIONABLE:1",
                "SOLUSDT:LONG:INVALIDATED:2",
                "SOLUSDT:LONG:ACTIONABLE:3",
            }
        await engine.dispose()

    asyncio.run(scenario())
