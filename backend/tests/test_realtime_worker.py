"""Coordinator behaviour: notify only on meaningful lifecycle transitions."""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.realtime.lifecycle import Confirmation
from backend.realtime.worker import MexcMonitoringWorker, MonitoringCoordinator


def test_coordinator_queues_actionable_transition_without_precommit_delivery():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        sent = []

        async def sender(user_id, confirmation, evaluation):
            sent.append((user_id, confirmation.symbol, evaluation.state.value))

        ready = Confirmation("SOLUSDT", "LONG", True, True, False, True, True, True)
        actionable = Confirmation("SOLUSDT", "LONG", True, True, True, True, True, True)
        async with factory() as session:
            coordinator = MonitoringCoordinator(sender)
            await coordinator.process(session, 3, ready)
            await coordinator.process(session, 3, actionable)
            await coordinator.process(session, 3, actionable)
            await session.commit()

        assert sent == []
        await engine.dispose()

    asyncio.run(scenario())


def test_worker_maps_usd_watchlist_symbols_to_mexc_usdt_perpetuals():
    async def scenario() -> None:
        worker = MexcMonitoringWorker()
        catalogue = frozenset({"BTC_USDT"})
        assert worker._supported_watchlist_symbol("BTC/USDT", catalogue) == "BTCUSDT"
        assert worker._supported_watchlist_symbol("BTC_USDT", catalogue) == "BTCUSDT"
        assert worker._supported_watchlist_symbol("BTC-USD", catalogue) == "BTCUSDT"
        assert worker._supported_watchlist_symbol("SNDK-USD", catalogue) is None
        assert worker._supported_watchlist_symbol("AAPL", catalogue) is None

    asyncio.run(scenario())
