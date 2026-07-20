"""MEXC Contract catalogue validation tests.

These tests never make a live network request. HTTP responses are supplied via
``httpx.MockTransport`` at the public REST boundary.
"""

import asyncio
from datetime import datetime

import httpx

from backend.realtime.mexc_contracts import (
    classify_market_scope,
    fetch_mexc_contract_catalogue,
    reset_mexc_contract_catalogue_cache,
)
from backend.realtime.worker import MexcMonitoringWorker
from backend.schemas import WatchlistPairWithScore


def test_classifier_requires_candidate_contract_to_appear_in_supplied_catalogue():
    catalogue = frozenset({"BTC_USDT", "ETH_USDT"})

    assert classify_market_scope("BTC-USD", catalogue) == ("mexc_realtime", "BTCUSDT")
    assert classify_market_scope("SNDK-USD", catalogue) == ("research_only", None)


def test_catalogue_fetch_uses_bounded_ttl_cache_with_mocked_http():
    async def scenario() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert request.url == httpx.URL("https://contract.mexc.com/api/v1/contract/detail")
            return httpx.Response(200, json={"success": True, "data": [{"symbol": "BTC_USDT"}]})

        reset_mexc_contract_catalogue_cache()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await fetch_mexc_contract_catalogue(client, ttl_seconds=60)
            second = await fetch_mexc_contract_catalogue(client, ttl_seconds=60)
            refreshed = await fetch_mexc_contract_catalogue(client, ttl_seconds=0)

        assert first == frozenset({"BTC_USDT"})
        assert second == first
        assert refreshed == first
        assert calls == 2

    asyncio.run(scenario())


def test_worker_never_subscribes_to_a_syntactically_valid_absent_contract():
    catalogue = frozenset({"BTC_USDT"})

    assert MexcMonitoringWorker._supported_watchlist_symbol("BTC-USD", catalogue) == "BTCUSDT"
    assert MexcMonitoringWorker._supported_watchlist_symbol("SNDK-USD", catalogue) is None


def test_watchlist_response_schema_includes_market_scope_and_mexc_symbol():
    response = WatchlistPairWithScore(
        id=1,
        user_id=1,
        pair="BTC-USD",
        sort_order=0,
        created_at=datetime.utcnow(),
        market_scope="mexc_realtime",
        mexc_symbol="BTCUSDT",
    )

    assert response.model_dump(include={"market_scope", "mexc_symbol"}) == {
        "market_scope": "mexc_realtime", "mexc_symbol": "BTCUSDT"
    }
