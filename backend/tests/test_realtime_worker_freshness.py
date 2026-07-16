import asyncio
import time

from backend.realtime.worker import MexcMonitoringWorker


def test_data_freshness_is_scoped_to_the_symbol_receiving_frames():
    async def verify() -> None:
        worker = MexcMonitoringWorker()
        worker._last_frame_by_symbol["BTCUSDT"] = time.monotonic()
        assert worker._is_symbol_fresh("BTCUSDT") is True
        assert worker._is_symbol_fresh("SOLUSDT") is False

    asyncio.run(verify())
