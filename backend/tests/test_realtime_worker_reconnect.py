import asyncio

from backend.realtime.worker import MexcMonitoringWorker


def test_worker_reconnect_wait_timeout_does_not_stop_worker():
    async def verify() -> None:
        worker = MexcMonitoringWorker()
        await worker._wait_to_reconnect(0.001)
        assert worker._stop.is_set() is False

    asyncio.run(verify())
