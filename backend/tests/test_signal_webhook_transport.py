"""Low-level fail-closed coverage for the signed webhook transport."""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import httpx
import pytest

from backend.alerts.webhook import (
    _CoreResponseStream,
    _DNS_ADMISSION,
    _DNS_EXECUTOR,
    _PinnedAsyncHTTPTransport,
    _PinnedNetworkBackend,
    _resolve_hostname,
    _resolve_public_addresses,
    send_signal_webhook,
    validate_webhook_config,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "webhook_url",
    [
        "",
        "https:///missing-host",
        "https://example.local/hook",
        "https://example.internal/hook",
        "https://example.com:not-a-port/hook",
        "https://example.com/" + "x" * 2048,
    ],
)
def test_config_rejects_empty_malformed_reserved_and_oversized_urls(webhook_url):
    with pytest.raises(ValueError):
        validate_webhook_config(
            {"webhook_url": webhook_url, "signing_secret": "s" * 32}
        )


async def test_literal_ip_resolution_and_duplicate_dns_answers():
    assert await _resolve_public_addresses("https://8.8.8.8/hook") == ("8.8.8.8",)
    assert await _resolve_public_addresses("https://127.0.0.1/hook") is None

    duplicate_records = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("93.184.216.34", 443)),
    ]
    with patch(
        "backend.alerts.webhook._resolve_hostname",
        AsyncMock(return_value=duplicate_records),
    ):
        assert await _resolve_public_addresses("https://example.com/hook") == (
            "93.184.216.34",
        )


@pytest.mark.parametrize(
    "resolver_error",
    [
        OSError("resolver failed"),
        UnicodeError("bad hostname"),
        ValueError("bad record"),
        asyncio.TimeoutError(),
    ],
)
async def test_resolver_failures_return_no_destination(resolver_error):
    with patch(
        "backend.alerts.webhook._resolve_hostname",
        AsyncMock(side_effect=resolver_error),
    ):
        assert await _resolve_public_addresses("https://example.com/hook") is None


async def test_empty_dns_answer_returns_no_destination():
    with patch(
        "backend.alerts.webhook._resolve_hostname",
        AsyncMock(return_value=[]),
    ):
        assert await _resolve_public_addresses("https://example.com/hook") is None


async def test_dns_answer_rejects_deprecated_ipv6_site_local_range():
    records = [(10, 1, 6, "", ("fec0::1", 443, 0, 0))]
    with patch(
        "backend.alerts.webhook._resolve_hostname",
        AsyncMock(return_value=records),
    ):
        assert await _resolve_public_addresses("https://example.com/hook") is None


async def test_executor_submission_failure_releases_dns_admission():
    admission = asyncio.Semaphore(1)
    fake_loop = MagicMock()
    fake_loop.run_in_executor.side_effect = RuntimeError("executor unavailable")

    with (
        patch("backend.alerts.webhook._DNS_ADMISSION", admission),
        patch(
            "backend.alerts.webhook.asyncio.get_running_loop",
            return_value=fake_loop,
        ),
    ):
        with pytest.raises(RuntimeError, match="executor unavailable"):
            await _resolve_hostname("example.com")

    assert admission._value == 1


async def test_dns_timeout_holds_admission_until_worker_future_finishes():
    actual_loop = asyncio.get_running_loop()
    worker_future = actual_loop.create_future()
    fake_loop = MagicMock()
    fake_loop.run_in_executor.return_value = worker_future
    admission = asyncio.Semaphore(1)

    with (
        patch("backend.alerts.webhook._DNS_ADMISSION", admission),
        patch("backend.alerts.webhook.DNS_TIMEOUT_SECONDS", 0.01),
        patch(
            "backend.alerts.webhook.asyncio.get_running_loop",
            return_value=fake_loop,
        ),
    ):
        with pytest.raises(asyncio.TimeoutError):
            await _resolve_hostname("example.com")
        assert admission.locked()
        worker_future.set_result([])
        await asyncio.sleep(0)

    assert admission._value == 1


async def test_resolver_uses_dedicated_executor_and_https_port():
    actual_loop = asyncio.get_running_loop()
    completed = actual_loop.create_future()
    completed.set_result([(2, 1, 6, "", ("93.184.216.34", 443))])
    fake_loop = MagicMock()
    fake_loop.run_in_executor.return_value = completed

    with patch(
        "backend.alerts.webhook.asyncio.get_running_loop", return_value=fake_loop
    ):
        records = await _resolve_hostname("example.com")

    assert records[0][4][0] == "93.184.216.34"
    fake_loop.run_in_executor.assert_called_once_with(
        _DNS_EXECUTOR,
        socket.getaddrinfo,
        "example.com",
        443,
        0,
        socket.SOCK_STREAM,
    )


async def test_pinned_backend_falls_back_across_validated_addresses():
    backend = _PinnedNetworkBackend(
        "example.com",
        ("93.184.216.34", "93.184.216.35"),
    )
    stream = MagicMock(spec=httpcore.AsyncNetworkStream)
    backend._backend.connect_tcp = AsyncMock(
        side_effect=[httpcore.ConnectError("first failed"), stream]
    )

    assert await backend.connect_tcp("example.com", 443) is stream
    assert backend._backend.connect_tcp.await_count == 2


async def test_pinned_backend_rejects_empty_and_all_failed_address_sets():
    empty = _PinnedNetworkBackend("example.com", ())
    with pytest.raises(httpcore.ConnectError, match="no validated addresses"):
        await empty.connect_tcp("example.com", 443)

    failed = _PinnedNetworkBackend(
        "example.com",
        ("93.184.216.34", "93.184.216.35"),
    )
    failed._backend.connect_tcp = AsyncMock(
        side_effect=[
            httpcore.ConnectError("first failed"),
            httpcore.ConnectTimeout("second timed out"),
        ]
    )
    with pytest.raises(httpcore.ConnectTimeout, match="second timed out"):
        await failed.connect_tcp("example.com", 443)


async def test_pinned_backend_disables_unix_sockets_and_delegates_sleep():
    backend = _PinnedNetworkBackend("example.com", ("93.184.216.34",))
    with pytest.raises(httpcore.ConnectError, match="Unix sockets are disabled"):
        await backend.connect_unix_socket("/tmp/unsafe.sock")

    backend._backend.sleep = AsyncMock()
    await backend.sleep(0.01)
    backend._backend.sleep.assert_awaited_once_with(0.01)


async def test_core_response_stream_iterates_and_closes_without_buffering():
    class CoreStream:
        def __init__(self):
            self.closed = False

        async def __aiter__(self):
            for chunk in (b"one", b"two"):
                yield chunk

        async def aclose(self):
            self.closed = True

    core_stream = CoreStream()
    stream = _CoreResponseStream(core_stream)

    assert [chunk async for chunk in stream] == [b"one", b"two"]
    await stream.aclose()
    assert core_stream.closed is True


@pytest.mark.parametrize(
    ("core_error", "httpx_error"),
    [
        (httpcore.ReadTimeout("slow"), httpx.TimeoutException),
        (httpcore.ConnectError("failed"), httpx.TransportError),
        (httpcore.RemoteProtocolError("bad response"), httpx.TransportError),
    ],
)
async def test_pinned_transport_translates_httpcore_errors(core_error, httpx_error):
    transport = _PinnedAsyncHTTPTransport(
        "https://example.com/hook",
        ("93.184.216.34",),
    )
    transport._pool.handle_async_request = AsyncMock(side_effect=core_error)
    request = httpx.Request("POST", "https://example.com/hook", content=b"{}")

    with pytest.raises(httpx_error):
        await transport.handle_async_request(request)
    await transport.aclose()


async def test_pinned_transport_rejects_sync_only_request_stream():
    class SyncOnlyStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"{}"

    transport = _PinnedAsyncHTTPTransport(
        "https://example.com/hook",
        ("93.184.216.34",),
    )
    request = httpx.Request(
        "POST",
        "https://example.com/hook",
        stream=SyncOnlyStream(),
    )

    with pytest.raises(TypeError, match="must be asynchronous"):
        await transport.handle_async_request(request)
    await transport.aclose()


async def test_delivery_rejects_invalid_config_and_nonserializable_payload_pre_dns():
    with patch("backend.alerts.webhook._resolve_public_addresses") as resolver:
        invalid_config = await send_signal_webhook(
            webhook_url="http://example.com/hook",
            signing_secret="s" * 32,
            payload={"event": "signal.created"},
        )
        invalid_payload = await send_signal_webhook(
            webhook_url="https://example.com/hook",
            signing_secret="s" * 32,
            payload={"event": "signal.created", "data": {"value": object()}},
        )

    assert invalid_config.error == "invalid_config"
    assert invalid_payload.error == "invalid_payload"
    resolver.assert_not_called()
