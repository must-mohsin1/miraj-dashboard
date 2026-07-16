"""Persistence behaviour for restart-safe real-time signal state."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import RealtimeSignal
from backend.realtime.lifecycle import SignalEvaluation, SignalState
from backend.realtime.store import record_transition


def test_record_transition_is_idempotent_for_the_same_state_and_updates_on_change():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        actionable = SignalEvaluation(SignalState.ACTIONABLE, True, "SOLUSDT:LONG:ACTIONABLE", ())
        invalidated = SignalEvaluation(SignalState.INVALIDATED, False, "SOLUSDT:LONG:INVALIDATED", ())
        async with factory() as session:
            first = await record_transition(session, 9, "SOLUSDT", "LONG", actionable)
            duplicate = await record_transition(session, 9, "SOLUSDT", "LONG", actionable)
            changed = await record_transition(session, 9, "SOLUSDT", "LONG", invalidated)
            recurring = await record_transition(session, 9, "SOLUSDT", "LONG", actionable)
            await session.commit()

            rows = (await session.execute(select(RealtimeSignal))).scalars().all()
            assert first.changed is True
            assert duplicate.changed is False
            assert changed.changed is True
            assert recurring.changed is True
            assert len(rows) == 1
            assert rows[0].state == "ACTIONABLE"
            assert rows[0].dedup_key == "SOLUSDT:LONG:ACTIONABLE:3"
            assert rows[0].transition_count == 3
        await engine.dispose()

    asyncio.run(scenario())
