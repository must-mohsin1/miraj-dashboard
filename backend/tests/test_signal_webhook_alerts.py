"""Signed signal webhook delivery and alert-manager integration tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import httpcore
import httpx
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend.alerts.manager import _process_single_result, process_scan_results
from backend.alerts.webhook import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    WebhookDeliveryResult,
    _PinnedAsyncHTTPTransport,
    _PinnedNetworkBackend,
    _destination_is_public,
    _resolve_public_addresses,
    build_signal_delivery_id,
    build_signal_event,
    send_signal_webhook,
    serialize_payload,
    validate_webhook_config,
    validate_webhook_destination,
)
from backend.alerts.webhook_outbox import QueuedSignalWebhook
from backend.routes.decision_desk import _channel_is_configured
from backend.routes.settings import (
    _parse_settings_json,
    _public_channel_config,
    _validate_alert_channel_config,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_validate_webhook_config_rejects_non_https_and_private_hosts():
    secret = "s" * 32
    for url in (
        "http://example.com/hook",
        "https://localhost/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.4/hook",
        "https://example.com:8443/hook",
    ):
        with pytest.raises(ValueError):
            validate_webhook_config({"webhook_url": url, "signing_secret": secret})


@pytest.mark.parametrize(
    "config",
    [
        {"webhook_url": "https://user@example.com/hook", "signing_secret": "s" * 32},
        {
            "webhook_url": "https://example.com/hook#fragment",
            "signing_secret": "s" * 32,
        },
        {"webhook_url": "https://example.com/hook", "signing_secret": "short"},
        {"webhook_url": "https://example.com/hook", "signing_secret": "s" * 1025},
        {"webhook_url": "https://example.com/hook", "signing_secret": " " + "s" * 32},
        {"webhook_url": "https://example.com/hook", "signing_secret": 123},
    ],
)
def test_validate_webhook_config_rejects_credentials_fragments_and_bad_secrets(config):
    with pytest.raises(ValueError):
        validate_webhook_config(config)


def test_validate_webhook_config_accepts_public_https_shape():
    config = {
        "webhook_url": "https://hooks.example.com/miraj?source=scan",
        "signing_secret": "s" * 32,
    }
    assert validate_webhook_config(config) == (
        config["webhook_url"],
        config["signing_secret"],
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/hook\x00",
        "https://example.com/hook\nnext",
        " https://example.com/hook",
    ],
)
def test_validate_webhook_config_rejects_parser_differentials(url):
    with pytest.raises(ValueError):
        validate_webhook_config({"webhook_url": url, "signing_secret": "s" * 32})


async def test_delivery_returns_invalid_config_for_non_printable_url():
    result = await send_signal_webhook(
        webhook_url="https://example.com/hook\x00",
        signing_secret="s" * 32,
        payload={"event": "signal.created"},
        delivery_id="invalid-url",
    )

    assert result == WebhookDeliveryResult(
        False,
        "invalid-url",
        error="invalid_config",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://224.0.0.1/hook",
        "https://[ff02::1]/hook",
        "https://192.0.0.8/hook",
        "https://[2002:7f00:1::]/hook",
        "https://[64:ff9b::c0a8:1]/hook",
        "https://[fec0::1]/hook",
    ],
)
async def test_destination_rejects_multicast_special_and_transition_addresses(url):
    assert await _resolve_public_addresses(url) is None


def test_build_signal_event_exposes_only_normalized_confirmed_fields():
    payload = build_signal_event(
        symbol="BTCUSDT",
        score=83.5,
        direction="LONG",
        entry=65000.0,
        stop_loss=64000.0,
        target=68000.0,
        rationale="Confirmed setup",
        sent_at=datetime(2026, 8, 9, 7, 30, tzinfo=timezone.utc),
    )

    assert payload == {
        "event": "signal.created",
        "dateKey": "2026-08-09",
        "sentAt": "2026-08-09T07:30:00Z",
        "data": {
            "signal": {
                "symbol": "BTCUSDT",
                "score": 83.5,
                "direction": "LONG",
                "tradeDecision": "confirmed",
                "entry": 65000.0,
                "stopLoss": 64000.0,
                "target": 68000.0,
                "rationale": "Confirmed setup",
            }
        },
    }


def test_signal_event_omits_null_optionals_and_serializes_unicode():
    payload = build_signal_event(
        symbol="BTCUSDT",
        score=0.0,
        direction="LONG",
        rationale=None,
        sent_at=datetime(2026, 8, 9, 7, 30),
    )

    signal = payload["data"]["signal"]
    assert not {"entry", "stopLoss", "target", "rationale"} & signal.keys()
    assert payload["sentAt"] == "2026-08-09T07:30:00Z"
    assert serialize_payload({"rationale": "确认"}) == '{"rationale":"确认"}'.encode()


def test_delivery_id_is_stable_for_retries_but_distinct_for_later_scans():
    first = build_signal_event(
        symbol="BTCUSDT",
        score=83.5,
        direction="LONG",
        sent_at=datetime(2026, 8, 9, 7, 30, tzinfo=timezone.utc),
    )
    retry_payload = json.loads(json.dumps(first))
    later_scan = build_signal_event(
        symbol="BTCUSDT",
        score=83.5,
        direction="LONG",
        sent_at=datetime(2026, 8, 9, 8, 30, tzinfo=timezone.utc),
    )
    changed = build_signal_event(
        symbol="BTCUSDT",
        score=84.0,
        direction="LONG",
        sent_at=datetime(2026, 8, 9, 8, 30, tzinfo=timezone.utc),
    )

    first_id = build_signal_delivery_id(user_id=7, channel_id=41, payload=first)
    retry_id = build_signal_delivery_id(user_id=7, channel_id=41, payload=retry_payload)
    later_id = build_signal_delivery_id(user_id=7, channel_id=41, payload=later_scan)
    changed_id = build_signal_delivery_id(user_id=7, channel_id=41, payload=changed)

    assert first_id == retry_id
    assert first_id != later_id
    assert first_id != changed_id
    UUID(first_id)


def test_settings_response_redacts_webhook_signing_secret():
    config = _public_channel_config(
        "webhook",
        {
            "webhook_url": "https://hooks.example.com/miraj",
            "signing_secret": "z" * 32,
        },
    )

    assert config == {
        "webhook_url": "https://hooks.example.com/miraj",
        "has_signing_secret": True,
    }

    assert _public_channel_config(
        "webhook", {"webhook_url": "https://example.com"}
    ) == {
        "webhook_url": "https://example.com",
        "has_signing_secret": False,
    }
    telegram_config = {"chat_id": "123"}
    assert _public_channel_config("telegram", telegram_config) is telegram_config


def test_decision_desk_recognizes_complete_webhook_config_only():
    complete = SimpleNamespace(
        channel_type="webhook",
        config=json.dumps(
            {
                "webhook_url": "https://hooks.example.com/miraj",
                "signing_secret": "s" * 32,
            }
        ),
    )
    missing_secret = SimpleNamespace(
        channel_type="webhook",
        config=json.dumps({"webhook_url": "https://hooks.example.com/miraj"}),
    )
    assert _channel_is_configured(complete) is True
    assert _channel_is_configured(missing_secret) is False


def test_settings_json_parser_preserves_channel_config():
    assert _parse_settings_json(
        '{"webhook_url":"https://hooks.example.com/miraj"}'
    ) == {"webhook_url": "https://hooks.example.com/miraj"}


async def test_destination_rejects_mixed_public_and_private_dns_answers():
    records = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("10.0.0.7", 443)),
    ]
    with patch(
        "backend.alerts.webhook._resolve_hostname",
        AsyncMock(return_value=records),
    ):
        assert not await _destination_is_public("https://hooks.example.com/miraj")


async def test_destination_accepts_only_public_dns_answers_and_rejects_bad_records():
    public_records = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
    ]
    with patch(
        "backend.alerts.webhook._resolve_hostname",
        AsyncMock(return_value=public_records),
    ):
        assert await _resolve_public_addresses("https://hooks.example.com/miraj") == (
            "93.184.216.34",
            "2606:2800:220:1:248:1893:25c8:1946",
        )

    with patch(
        "backend.alerts.webhook._resolve_hostname",
        AsyncMock(return_value=[(2, 1, 6, "", ())]),
    ):
        assert (
            await _resolve_public_addresses("https://hooks.example.com/miraj") is None
        )

    with patch(
        "backend.alerts.webhook._resolve_hostname",
        AsyncMock(side_effect=asyncio.TimeoutError),
    ):
        assert (
            await _resolve_public_addresses("https://hooks.example.com/miraj") is None
        )


async def test_destination_validation_rejects_unresolvable_hostname():
    with patch(
        "backend.alerts.webhook._resolve_public_addresses",
        AsyncMock(return_value=None),
    ):
        with pytest.raises(ValueError, match="resolve exclusively to public"):
            await validate_webhook_destination(
                {
                    "webhook_url": "https://hooks.example.com/miraj",
                    "signing_secret": "s" * 32,
                }
            )


async def test_destination_validation_accepts_public_resolution():
    config = {
        "webhook_url": "https://hooks.example.com/miraj",
        "signing_secret": "s" * 32,
    }
    with patch(
        "backend.alerts.webhook._resolve_public_addresses",
        AsyncMock(return_value=("93.184.216.34",)),
    ):
        assert await validate_webhook_destination(config) == (
            config["webhook_url"],
            config["signing_secret"],
        )


async def test_settings_validator_maps_destination_errors_to_422():
    with patch(
        "backend.routes.settings.validate_webhook_destination",
        AsyncMock(side_effect=ValueError("unsafe destination")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _validate_alert_channel_config(
                "webhook",
                {
                    "webhook_url": "https://hooks.example.com/miraj",
                    "signing_secret": "s" * 32,
                },
            )

    assert exc_info.value.status_code == 422
    await _validate_alert_channel_config("telegram", {})


async def test_pinned_network_backend_connects_only_to_validated_address():
    backend = _PinnedNetworkBackend("hooks.example.com", ("93.184.216.34",))
    stream = MagicMock(spec=httpcore.AsyncNetworkStream)
    backend._backend.connect_tcp = AsyncMock(return_value=stream)

    result = await backend.connect_tcp("hooks.example.com", 443, timeout=2.0)

    assert result is stream
    backend._backend.connect_tcp.assert_awaited_once_with(
        "93.184.216.34",
        443,
        timeout=2.0,
        local_address=None,
        socket_options=None,
    )
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("rebound.example.com", 443)


async def test_pinned_transport_preserves_original_origin_for_tls_and_host_header():
    transport = _PinnedAsyncHTTPTransport(
        "https://hooks.example.com/miraj",
        ("93.184.216.34",),
    )
    core_stream = httpcore.AsyncMockStream([b"ignored response body"])
    transport._pool.handle_async_request = AsyncMock(
        return_value=SimpleNamespace(
            status=204,
            headers=[],
            stream=core_stream,
            extensions={},
        )
    )
    request = httpx.Request(
        "POST",
        "https://hooks.example.com/miraj",
        content=b"{}",
    )

    response = await transport.handle_async_request(request)

    assert response.status_code == 204
    core_request = transport._pool.handle_async_request.await_args.args[0]
    assert core_request.url.host == b"hooks.example.com"
    assert (b"Host", b"hooks.example.com") in core_request.headers
    await response.aclose()
    await transport.aclose()


async def test_send_signal_webhook_signs_the_exact_bytes_sent():
    secret = "a" * 32
    delivered_at = datetime(2026, 8, 9, 7, 30, tzinfo=timezone.utc)
    payload = build_signal_event(
        symbol="ETHUSDT",
        score=74.0,
        direction="SHORT",
        sent_at=delivered_at,
    )
    response = MagicMock(status_code=202)
    response.aread = AsyncMock(side_effect=AssertionError("response body was buffered"))
    response_context = AsyncMock()
    response_context.__aenter__.return_value = response
    response_context.__aexit__.return_value = False
    client = MagicMock()
    client.stream.return_value = response_context
    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = client
    context_manager.__aexit__.return_value = False

    with (
        patch(
            "backend.alerts.webhook._resolve_public_addresses",
            AsyncMock(return_value=("93.184.216.34",)),
        ),
        patch("backend.alerts.webhook.httpx.AsyncClient", return_value=context_manager),
    ):
        result = await send_signal_webhook(
            webhook_url="https://hooks.example.com/miraj",
            signing_secret=secret,
            payload=payload,
            delivery_id="delivery-123",
            delivered_at=delivered_at,
        )

    assert result == WebhookDeliveryResult(True, "delivery-123", status_code=202)
    args, kwargs = client.stream.call_args
    assert args[:2] == ("POST", "https://hooks.example.com/miraj")
    raw_body = kwargs["content"]
    headers = kwargs["headers"]
    expected_timestamp = str(int(delivered_at.timestamp() * 1000))
    expected_signature = hmac.new(
        secret.encode(),
        expected_timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    assert json.loads(raw_body) == payload
    assert headers[EVENT_HEADER] == "signal.created"
    assert headers[DELIVERY_HEADER] == "delivery-123"
    assert headers[TIMESTAMP_HEADER] == expected_timestamp
    assert headers[SIGNATURE_HEADER] == expected_signature
    response.aread.assert_not_awaited()


async def test_send_signal_webhook_fails_closed_for_non_json_numbers():
    with (
        patch("backend.alerts.webhook._resolve_public_addresses") as resolver,
        patch("backend.alerts.webhook.httpx.AsyncClient") as client,
    ):
        result = await send_signal_webhook(
            webhook_url="https://hooks.example.com/miraj",
            signing_secret="a" * 32,
            payload={"event": "signal.created", "data": {"score": float("nan")}},
            delivery_id="invalid-payload",
        )

    assert result == WebhookDeliveryResult(
        False,
        "invalid-payload",
        error="invalid_payload",
    )
    resolver.assert_not_called()
    client.assert_not_called()


async def test_send_signal_webhook_rejects_invalid_event_without_resolving():
    with patch("backend.alerts.webhook._resolve_public_addresses") as resolver:
        result = await send_signal_webhook(
            webhook_url="https://hooks.example.com/miraj",
            signing_secret="a" * 32,
            payload={"event": "other.event"},
            delivery_id="invalid-event",
        )

    assert result.error == "invalid_payload"
    resolver.assert_not_called()


async def test_send_signal_webhook_fails_closed_when_destination_turns_unsafe():
    with (
        patch(
            "backend.alerts.webhook._resolve_public_addresses",
            AsyncMock(return_value=None),
        ),
        patch("backend.alerts.webhook.httpx.AsyncClient") as client,
    ):
        result = await send_signal_webhook(
            webhook_url="https://hooks.example.com/miraj",
            signing_secret="a" * 32,
            payload={"event": "signal.created"},
            delivery_id="unsafe-destination",
        )

    assert result == WebhookDeliveryResult(
        False,
        "unsafe-destination",
        error="unsafe_destination",
    )
    client.assert_not_called()


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [(400, "http_error"), (503, "http_error")],
)
async def test_send_signal_webhook_maps_http_rejections(status_code, expected_error):
    response_context = AsyncMock()
    response_context.__aenter__.return_value = MagicMock(status_code=status_code)
    client = MagicMock()
    client.stream.return_value = response_context
    client_context = AsyncMock()
    client_context.__aenter__.return_value = client

    with (
        patch(
            "backend.alerts.webhook._resolve_public_addresses",
            AsyncMock(return_value=("93.184.216.34",)),
        ),
        patch("backend.alerts.webhook.httpx.AsyncClient", return_value=client_context),
    ):
        result = await send_signal_webhook(
            webhook_url="https://hooks.example.com/miraj",
            signing_secret="a" * 32,
            payload={"event": "signal.created"},
            delivery_id=f"http-{status_code}",
        )

    assert result == WebhookDeliveryResult(
        False,
        f"http-{status_code}",
        status_code=status_code,
        error=expected_error,
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.TimeoutException("slow receiver"), "timeout"),
        (httpx.ConnectError("connection refused"), "transport_error"),
    ],
)
async def test_send_signal_webhook_maps_transport_failures(error, expected):
    client = MagicMock()
    client.stream.side_effect = error
    client_context = AsyncMock()
    client_context.__aenter__.return_value = client

    with (
        patch(
            "backend.alerts.webhook._resolve_public_addresses",
            AsyncMock(return_value=("93.184.216.34",)),
        ),
        patch("backend.alerts.webhook.httpx.AsyncClient", return_value=client_context),
    ):
        result = await send_signal_webhook(
            webhook_url="https://hooks.example.com/miraj",
            signing_secret="a" * 32,
            payload={"event": "signal.created"},
            delivery_id="transport-failure",
        )

    assert result.success is False
    assert result.error == expected


async def test_send_signal_webhook_generates_uuid_delivery_id():
    with (
        patch(
            "backend.alerts.webhook._resolve_public_addresses",
            AsyncMock(return_value=None),
        ),
    ):
        result = await send_signal_webhook(
            webhook_url="https://hooks.example.com/miraj",
            signing_secret="a" * 32,
            payload={"event": "signal.created"},
        )

    assert str(UUID(result.delivery_id)) == result.delivery_id


async def test_send_signal_webhook_enforces_total_delivery_deadline():
    async def stalled_resolution(_webhook_url):
        await asyncio.Event().wait()

    with (
        patch(
            "backend.alerts.webhook._resolve_public_addresses",
            side_effect=stalled_resolution,
        ),
        patch("backend.alerts.webhook.DELIVERY_TIMEOUT_SECONDS", 0.01),
    ):
        result = await send_signal_webhook(
            webhook_url="https://hooks.example.com/miraj",
            signing_secret="a" * 32,
            payload={"event": "signal.created"},
            delivery_id="hard-deadline",
        )

    assert result == WebhookDeliveryResult(
        False,
        "hard-deadline",
        error="timeout",
    )


async def test_alert_manager_routes_only_confirmed_signal_to_webhook():
    channel = SimpleNamespace(
        id=41,
        channel_type="webhook",
        config=json.dumps(
            {
                "webhook_url": "https://hooks.example.com/miraj",
                "signing_secret": "z" * 32,
            }
        ),
    )
    session = MagicMock()
    scan_result = {
        "symbol": "SOLUSDT",
        "confluence_score": 88.0,
        "trade_plan": {
            "trade_decision": True,
            "direction": "LONG",
            "entry": 145.0,
            "stop_loss": 139.0,
            "target_1": 157.0,
            "reasoning": "Confirmed multi-timeframe setup",
        },
    }
    delivery = QueuedSignalWebhook("delivery-abc", created=True)

    with (
        patch("backend.alerts.manager._count_recent_alerts", AsyncMock(return_value=0)),
        patch(
            "backend.alerts.manager.enqueue_signal_webhook",
            AsyncMock(return_value=delivery),
        ) as sender,
    ):
        outcome = await _process_single_result(
            session,
            7,
            scan_result,
            [channel],
            {},
        )

    assert outcome == {
        "user_id": 7,
        "pair": "SOLUSDT",
        "score": 88.0,
        "channels_sent": [],
        "channels_queued": ["webhook"],
        "status": "queued",
    }
    sender.assert_awaited_once()
    queued_payload = sender.await_args.kwargs["payload"]
    assert queued_payload["data"]["signal"]["tradeDecision"] == "confirmed"
    session.add.assert_not_called()


async def test_alert_manager_does_not_webhook_unconfirmed_plan():
    channel = SimpleNamespace(
        id=42,
        channel_type="webhook",
        config=json.dumps(
            {
                "webhook_url": "https://hooks.example.com/miraj",
                "signing_secret": "z" * 32,
            }
        ),
    )
    with patch("backend.alerts.manager.enqueue_signal_webhook", AsyncMock()) as sender:
        outcome = await _process_single_result(
            MagicMock(),
            7,
            {
                "symbol": "SOLUSDT",
                "confluence_score": 99.0,
                "trade_plan": {"trade_decision": False},
            },
            [channel],
            {},
        )

    assert outcome is None
    sender.assert_not_awaited()


async def test_alert_manager_audits_webhook_queue_limit():
    channel = SimpleNamespace(
        id=43,
        channel_type="webhook",
        config=json.dumps(
            {
                "webhook_url": "https://hooks.example.com/miraj",
                "signing_secret": "z" * 32,
            }
        ),
    )
    session = MagicMock()
    with (
        patch("backend.alerts.manager._count_recent_alerts", AsyncMock(return_value=0)),
        patch(
            "backend.alerts.manager.enqueue_signal_webhook",
            AsyncMock(return_value=None),
        ),
    ):
        outcome = await _process_single_result(
            session,
            7,
            {
                "symbol": "SOLUSDT",
                "confluence_score": 88.0,
                "trade_plan": {"trade_decision": True, "direction": "LONG"},
            },
            [channel],
            {},
        )

    assert outcome["channels_sent"] == []
    assert outcome["status"] == "failed"
    history = session.add.call_args.args[0]
    assert history.status == "failed"
    audit = json.loads(history.message)
    assert audit == {"error": "queue_limit"}


@pytest.mark.parametrize("raw_config", [None, "not-json", "{}"])
async def test_alert_manager_audits_missing_or_malformed_webhook_config(raw_config):
    channel = SimpleNamespace(
        id=44,
        channel_type="webhook",
        config=raw_config,
    )
    session = MagicMock()
    with (
        patch("backend.alerts.manager._count_recent_alerts", AsyncMock(return_value=0)),
        patch("backend.alerts.manager.enqueue_signal_webhook", AsyncMock()) as sender,
    ):
        outcome = await _process_single_result(
            session,
            7,
            {
                "symbol": "SOLUSDT",
                "confluence_score": 88.0,
                "trade_plan": {"trade_decision": True, "direction": "LONG"},
            },
            [channel],
            {},
        )

    sender.assert_not_awaited()
    assert outcome["status"] == "failed"
    history = session.add.call_args.args[0]
    assert history.channel == "webhook"
    assert history.status == "failed"
    assert history.message == ""


async def test_alert_manager_respects_pair_disabled_setting_before_webhook_delivery():
    channel = SimpleNamespace(
        id=45,
        channel_type="webhook",
        config=json.dumps(
            {
                "webhook_url": "https://hooks.example.com/miraj",
                "signing_secret": "z" * 32,
            }
        ),
    )
    session = MagicMock()
    with patch("backend.alerts.manager.enqueue_signal_webhook", AsyncMock()) as sender:
        outcome = await _process_single_result(
            session,
            7,
            {
                "symbol": "SOLUSDT",
                "confluence_score": 88.0,
                "trade_plan": {"trade_decision": True, "direction": "LONG"},
            },
            [channel],
            {"SOLUSDT": {"alert_enabled": False}},
        )

    assert outcome is None
    sender.assert_not_awaited()
    session.add.assert_not_called()


async def test_alert_manager_rejects_confirmed_signal_without_explicit_direction():
    channel = SimpleNamespace(
        id=46,
        channel_type="webhook",
        config=json.dumps(
            {
                "webhook_url": "https://hooks.example.com/miraj",
                "signing_secret": "z" * 32,
            }
        ),
    )
    with patch("backend.alerts.manager.enqueue_signal_webhook", AsyncMock()) as sender:
        outcome = await _process_single_result(
            MagicMock(),
            7,
            {
                "symbol": "SOLUSDT",
                "confluence_score": 88.0,
                "trade_plan": {"trade_decision": True},
            },
            [channel],
            {},
        )

    assert outcome is None
    sender.assert_not_awaited()


async def test_alert_manager_explicit_unavailable_channel_filter_sends_nothing():
    channel = SimpleNamespace(
        id=47,
        channel_type="webhook",
        config=json.dumps(
            {
                "webhook_url": "https://hooks.example.com/miraj",
                "signing_secret": "z" * 32,
            }
        ),
    )
    with (
        patch("backend.alerts.manager._count_recent_alerts", AsyncMock(return_value=0)),
        patch("backend.alerts.manager.enqueue_signal_webhook", AsyncMock()) as sender,
    ):
        outcome = await _process_single_result(
            MagicMock(),
            7,
            {
                "symbol": "SOLUSDT",
                "confluence_score": 88.0,
                "trade_plan": {"trade_decision": True, "direction": "LONG"},
            },
            [channel],
            {"SOLUSDT": {"notification_channels": ["telegram"]}},
        )

    assert outcome is None
    sender.assert_not_awaited()


async def test_alert_manager_uses_production_flat_trade_plan_for_outbox():
    channel = SimpleNamespace(
        id=48,
        channel_type="webhook",
        config=json.dumps(
            {
                "webhook_url": "https://hooks.example.com/miraj",
                "signing_secret": "z" * 32,
            }
        ),
    )
    delivery = QueuedSignalWebhook("stable-id", created=True)
    with (
        patch("backend.alerts.manager._count_recent_alerts", AsyncMock(return_value=0)),
        patch(
            "backend.alerts.manager.enqueue_signal_webhook",
            AsyncMock(return_value=delivery),
        ) as sender,
    ):
        await _process_single_result(
            MagicMock(),
            7,
            {
                "symbol": "SOLUSDT",
                "confluence_score": 88.0,
                "cached_at": "2026-08-09T07:30:00+00:00",
                "trade_plan": {
                    "trade_decision": True,
                    "direction": "LONG",
                    "entry_zone": {"low": 145.0, "high": 146.0},
                    "take_profit_targets": [{"level": 157.0}],
                },
                "trade_plan_flat": {
                    "direction": "LONG",
                    "entry": 145.0,
                    "stop_loss": 139.0,
                    "target_1": 157.0,
                    "rationale": "Production-normalized plan",
                },
            },
            [channel],
            {},
        )

    sent = sender.await_args.kwargs
    assert sent["payload"]["sentAt"] == "2026-08-09T07:30:00Z"
    assert sent["payload"]["data"]["signal"] == {
        "symbol": "SOLUSDT",
        "score": 88.0,
        "direction": "LONG",
        "tradeDecision": "confirmed",
        "entry": 145.0,
        "stopLoss": 139.0,
        "target": 157.0,
        "rationale": "Production-normalized plan",
    }
    assert sent["user_id"] == 7
    assert sent["channel_id"] == 48


async def test_alert_manager_isolates_unexpected_channel_delivery_failure():
    config = json.dumps(
        {
            "webhook_url": "https://hooks.example.com/miraj",
            "signing_secret": "z" * 32,
        }
    )
    channels = [
        SimpleNamespace(id=49, channel_type="webhook", config=config),
        SimpleNamespace(id=50, channel_type="webhook", config=config),
    ]
    successful = QueuedSignalWebhook("second-delivery", created=True)
    session = MagicMock()
    with (
        patch("backend.alerts.manager._count_recent_alerts", AsyncMock(return_value=0)),
        patch(
            "backend.alerts.manager.enqueue_signal_webhook",
            AsyncMock(side_effect=[RuntimeError("boom"), successful]),
        ) as sender,
    ):
        outcome = await _process_single_result(
            session,
            7,
            {
                "symbol": "SOLUSDT",
                "confluence_score": 88.0,
                "trade_plan": {"trade_decision": True, "direction": "LONG"},
            },
            channels,
            {},
        )

    assert sender.await_count == 2
    assert outcome["channels_sent"] == []
    assert outcome["channels_queued"] == ["webhook"]
    histories = [call.args[0] for call in session.add.call_args_list]
    assert [history.status for history in histories] == ["failed"]
    assert json.loads(histories[0].message)["error"] == "channel_error"


async def test_process_scan_results_deduplicates_same_pair_within_batch():
    channel = SimpleNamespace(id=51, channel_type="telegram", config="{}")
    outcome = {
        "user_id": 7,
        "pair": "SOLUSDT",
        "score": 88.0,
        "channels_sent": ["telegram"],
        "channels_queued": [],
        "status": "sent",
    }
    duplicate_results = [
        {"symbol": "SOLUSDT"},
        {"symbol": " solusdt "},
    ]
    with (
        patch(
            "backend.alerts.manager._get_enabled_channels",
            AsyncMock(return_value=[channel]),
        ),
        patch(
            "backend.alerts.manager._get_pair_settings_map",
            AsyncMock(return_value={}),
        ),
        patch(
            "backend.alerts.manager._process_single_result",
            AsyncMock(return_value=outcome),
        ) as processor,
    ):
        outcomes = await process_scan_results(
            MagicMock(),
            {7: duplicate_results},
        )

    assert outcomes == [outcome]
    processor.assert_awaited_once()
