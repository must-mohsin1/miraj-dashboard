"""Live watchlist refresh behaviour for the MEXC realtime worker."""

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.realtime.worker import MexcMonitoringWorker


def test_due_watchlist_refresh_replaces_membership_and_reports_change():
    async def scenario() -> None:
        worker = MexcMonitoringWorker()
        worker._users_by_symbol = defaultdict(set, {"BTCUSDT": {1}})
        worker._last_watchlist_refresh_at = 0.0
        worker._watchlist_refresh_seconds = 0.0

        async def reload_watchlist() -> None:
            # The refreshed, catalogue-filtered membership replaces—not merges
            # with—the existing stream subscriptions.
            worker._users_by_symbol = defaultdict(set, {"ETHUSDT": {2}})

        worker._load_watchlist = reload_watchlist  # type: ignore[method-assign]

        assert await worker._refresh_watchlist_if_due() is True
        assert worker._users_by_symbol == {"ETHUSDT": {2}}

    asyncio.run(scenario())


def test_watchlist_refresh_does_not_reload_before_its_interval():
    async def scenario() -> None:
        worker = MexcMonitoringWorker()
        worker._last_watchlist_refresh_at = float("inf")
        calls = 0

        async def reload_watchlist() -> None:
            nonlocal calls
            calls += 1

        worker._load_watchlist = reload_watchlist  # type: ignore[method-assign]

        assert await worker._refresh_watchlist_if_due() is False
        assert calls == 0

    asyncio.run(scenario())


def test_catalogue_outage_removes_previous_membership_fail_closed():
    async def scenario() -> None:
        worker = MexcMonitoringWorker()
        worker._users_by_symbol = defaultdict(set, {"BTCUSDT": {1}})
        with patch("backend.realtime.worker.fetch_mexc_contract_catalogue", new=AsyncMock(return_value=None)):
            await worker._load_watchlist()
        assert worker._users_by_symbol == {}

    asyncio.run(scenario())


def test_stream_requests_reconnect_only_when_due_refresh_changes_membership():
    class Socket:
        async def send(self, _payload: str) -> None:
            pass

        async def recv(self) -> str:
            return "{}"

    class Connection:
        async def __aenter__(self) -> Socket:
            return Socket()

        async def __aexit__(self, *_args: object) -> None:
            pass

    async def scenario(refresh_changed: bool) -> bool:
        worker = MexcMonitoringWorker()
        worker._users_by_symbol = defaultdict(set, {"BTCUSDT": {1}})

        refresh_calls = 0

        async def refresh() -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            if not refresh_changed and refresh_calls == 2:
                worker._stop.set()
            return refresh_changed

        worker._refresh_watchlist_if_due = refresh  # type: ignore[method-assign]
        websocket_module = SimpleNamespace(connect=lambda *_args, **_kwargs: Connection())
        with patch.dict("sys.modules", {"websockets": websocket_module}):
            return await worker._stream_once()

    assert asyncio.run(scenario(True)) is True
    assert asyncio.run(scenario(False)) is False
