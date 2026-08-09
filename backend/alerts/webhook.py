"""Signed outbound webhook delivery for confirmed Miraj signals.

Webhook channels intentionally receive only the normalized alert fields that
the existing Telegram/Discord/email paths expose.  Raw analysis payloads,
exchange credentials, and broker actions never cross this boundary.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from typing import Any, AsyncIterable, Optional
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpcore
import httpx

logger = logging.getLogger(__name__)

EVENT_NAME = "signal.created"
SIGNATURE_HEADER = "X-Miraj-Signature"
TIMESTAMP_HEADER = "X-Miraj-Timestamp"
DELIVERY_HEADER = "X-Miraj-Delivery"
EVENT_HEADER = "X-Miraj-Event"
MIN_SIGNING_SECRET_LENGTH = 32
MAX_SIGNING_SECRET_LENGTH = 1024
HTTPS_PORT = 443
MAX_WEBHOOK_URL_LENGTH = 2048
DNS_TIMEOUT_SECONDS = 5.0
DELIVERY_TIMEOUT_SECONDS = 15.0
DNS_MAX_IN_FLIGHT = 4
CONFIG_DNS_MAX_IN_FLIGHT = 2
_DNS_EXECUTOR = ThreadPoolExecutor(
    max_workers=DNS_MAX_IN_FLIGHT,
    thread_name_prefix="miraj-webhook-dns",
)
_DNS_ADMISSION = asyncio.Semaphore(DNS_MAX_IN_FLIGHT)
_CONFIG_DNS_EXECUTOR = ThreadPoolExecutor(
    max_workers=CONFIG_DNS_MAX_IN_FLIGHT,
    thread_name_prefix="miraj-webhook-config-dns",
)
_CONFIG_DNS_ADMISSION = asyncio.Semaphore(CONFIG_DNS_MAX_IN_FLIGHT)
_EXTRA_NON_PUBLIC_NETWORKS = (
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)


@dataclass(frozen=True)
class WebhookDeliveryResult:
    """Safe delivery metadata suitable for audit logs."""

    success: bool
    delivery_id: str
    status_code: Optional[int] = None
    error: Optional[str] = None


class _UnsafeDestinationError(Exception):
    """Raised when a delivery target is not exclusively public."""


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect an HTTP origin only to addresses validated by Miraj.

    HTTP Core still receives the original hostname, so it preserves the Host
    header, TLS SNI, and certificate verification.  Only the TCP destination is
    replaced, eliminating the second DNS lookup that enables DNS rebinding.
    """

    def __init__(self, expected_host: str, addresses: tuple[str, ...]) -> None:
        self._expected_host = expected_host.rstrip(".").lower()
        self._addresses = addresses
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        if host.rstrip(".").lower() != self._expected_host:
            raise httpcore.ConnectError("Unexpected webhook connection host")

        last_error: Optional[Exception] = None
        for address in self._addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("Webhook destination has no validated addresses")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: Optional[float] = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are disabled for webhooks")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _CoreResponseStream(httpx.AsyncByteStream):
    """Adapt HTTP Core's response stream to HTTPX without buffering it."""

    def __init__(self, stream: AsyncIterable[bytes]) -> None:
        self._stream = stream

    async def __aiter__(self):
        async for chunk in self._stream:
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()  # type: ignore[attr-defined]


class _PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """HTTPX transport backed by a one-request, DNS-pinned connection pool."""

    def __init__(self, webhook_url: str, addresses: tuple[str, ...]) -> None:
        parsed_url = _parse_safe_webhook_url(webhook_url)
        if parsed_url is None:
            raise httpx.InvalidURL("Unsafe webhook URL")
        expected_host = parsed_url.raw_host.decode("ascii")
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=1,
            max_keepalive_connections=0,
            keepalive_expiry=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedNetworkBackend(expected_host, addresses),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not isinstance(request.stream, httpx.AsyncByteStream):
            raise TypeError("Webhook request stream must be asynchronous")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self._pool.handle_async_request(core_request)
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException(str(exc), request=request) from exc
        except (
            httpcore.ConnectionNotAvailable,
            httpcore.NetworkError,
            httpcore.ProtocolError,
            httpcore.ProxyError,
            httpcore.UnsupportedProtocol,
        ) as exc:
            raise httpx.TransportError(str(exc), request=request) from exc
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_CoreResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def validate_webhook_config(config: dict[str, Any]) -> tuple[str, str]:
    """Validate and return ``(webhook_url, signing_secret)``.

    Generic outbound webhooks are restricted to public HTTPS destinations on
    the default TLS port. Delivery resolves immediately before the request and
    pins the TCP connection to those validated addresses.
    """
    webhook_url = config.get("webhook_url")
    signing_secret = config.get("signing_secret")
    if not isinstance(webhook_url, str) or not _has_safe_url_shape(webhook_url):
        raise ValueError(
            "webhook_url must be a public HTTPS URL on the default TLS port"
        )
    if (
        not isinstance(signing_secret, str)
        or len(signing_secret) < MIN_SIGNING_SECRET_LENGTH
        or len(signing_secret) > MAX_SIGNING_SECRET_LENGTH
        or signing_secret != signing_secret.strip()
    ):
        raise ValueError(
            f"signing_secret must contain {MIN_SIGNING_SECRET_LENGTH}-"
            f"{MAX_SIGNING_SECRET_LENGTH} characters and have no surrounding whitespace"
        )
    return webhook_url, signing_secret


async def validate_webhook_destination(
    config: dict[str, Any],
) -> tuple[str, str]:
    """Validate config and require a currently public DNS/IP destination."""
    webhook_url, signing_secret = validate_webhook_config(config)
    if not await _resolve_public_addresses(
        webhook_url,
        resolver=_resolve_config_hostname,
    ):
        raise ValueError("webhook_url must resolve exclusively to public IP addresses")
    return webhook_url, signing_secret


def build_signal_event(
    *,
    symbol: str,
    score: float,
    direction: str,
    entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    target: Optional[float] = None,
    rationale: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the stable public payload for an actionable Miraj signal."""
    now = _as_utc(sent_at or datetime.now(timezone.utc))
    signal: dict[str, Any] = {
        "symbol": symbol,
        "score": score,
        "direction": direction,
        "tradeDecision": "confirmed",
    }
    optional_fields = {
        "entry": entry,
        "stopLoss": stop_loss,
        "target": target,
        "rationale": rationale,
    }
    signal.update(
        {key: value for key, value in optional_fields.items() if value is not None}
    )
    return {
        "event": EVENT_NAME,
        "dateKey": now.date().isoformat(),
        "sentAt": now.isoformat().replace("+00:00", "Z"),
        "data": {"signal": signal},
    }


def serialize_payload(payload: dict[str, Any]) -> bytes:
    """Serialize deterministically; these exact bytes are signed and sent."""
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sign_payload(signing_secret: str, timestamp: str, raw_body: bytes) -> str:
    """Return HMAC-SHA256 for ``timestamp.raw_body``."""
    signed = timestamp.encode("utf-8") + b"." + raw_body
    return hmac.new(signing_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def build_signal_delivery_id(
    *,
    user_id: int,
    channel_id: int,
    payload: dict[str, Any],
) -> str:
    """Return a stable receiver idempotency key for one logical signal.

    ``sentAt`` is the stable source scan timestamp. The committed outbox stores
    the exact payload and reuses it for every retry, while a later scan with the
    same signal values still receives a distinct delivery ID.
    """
    logical_event = {
        "event": payload.get("event"),
        "dateKey": payload.get("dateKey"),
        "sentAt": payload.get("sentAt"),
        "data": payload.get("data"),
    }
    canonical = serialize_payload(logical_event).decode("utf-8")
    return str(
        uuid5(
            NAMESPACE_URL,
            f"miraj:signal:{user_id}:{channel_id}:{canonical}",
        )
    )


async def send_signal_webhook(
    *,
    webhook_url: str,
    signing_secret: str,
    payload: dict[str, Any],
    delivery_id: Optional[str] = None,
    delivered_at: Optional[datetime] = None,
) -> WebhookDeliveryResult:
    """Sign and POST one signal event without following redirects."""
    resolved_delivery_id = delivery_id or str(uuid4())
    try:
        validate_webhook_config(
            {"webhook_url": webhook_url, "signing_secret": signing_secret}
        )
    except ValueError:
        logger.warning("Signal webhook configuration is invalid; delivery skipped")
        return WebhookDeliveryResult(
            False, resolved_delivery_id, error="invalid_config"
        )

    now = _as_utc(delivered_at or datetime.now(timezone.utc))
    timestamp = str(int(now.timestamp() * 1000))
    try:
        if payload.get("event") != EVENT_NAME:
            raise ValueError("unexpected event")
        raw_body = serialize_payload(payload)
    except (TypeError, ValueError):
        logger.warning(
            "Signal webhook payload is not valid JSON; delivery skipped "
            "(delivery_id=%s)",
            resolved_delivery_id,
        )
        return WebhookDeliveryResult(
            False,
            resolved_delivery_id,
            error="invalid_payload",
        )
    headers = {
        "Content-Type": "application/json",
        EVENT_HEADER: EVENT_NAME,
        DELIVERY_HEADER: resolved_delivery_id,
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: sign_payload(signing_secret, timestamp, raw_body),
    }

    async def _deliver() -> int:
        addresses = await _resolve_public_addresses(webhook_url)
        if not addresses:
            raise _UnsafeDestinationError
        transport = _PinnedAsyncHTTPTransport(webhook_url, addresses)
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(DELIVERY_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST",
                webhook_url,
                content=raw_body,
                headers=headers,
            ) as response:
                return response.status_code

    try:
        status_code = await asyncio.wait_for(
            _deliver(),
            timeout=DELIVERY_TIMEOUT_SECONDS,
        )
        if 200 <= status_code < 300:
            logger.info(
                "Signal webhook delivered (delivery_id=%s, status=%d)",
                resolved_delivery_id,
                status_code,
            )
            return WebhookDeliveryResult(
                True,
                resolved_delivery_id,
                status_code=status_code,
            )
        logger.warning(
            "Signal webhook rejected (delivery_id=%s, status=%d)",
            resolved_delivery_id,
            status_code,
        )
        return WebhookDeliveryResult(
            False,
            resolved_delivery_id,
            status_code=status_code,
            error="http_error",
        )
    except _UnsafeDestinationError:
        logger.warning(
            "Signal webhook destination did not resolve exclusively to public IPs; delivery skipped"
        )
        return WebhookDeliveryResult(
            False,
            resolved_delivery_id,
            error="unsafe_destination",
        )
    except (asyncio.TimeoutError, httpx.TimeoutException):
        logger.warning(
            "Signal webhook timed out (delivery_id=%s)", resolved_delivery_id
        )
        return WebhookDeliveryResult(False, resolved_delivery_id, error="timeout")
    except (httpx.HTTPError, httpx.InvalidURL, UnicodeError, ValueError) as exc:
        logger.warning(
            "Signal webhook transport failed (delivery_id=%s, error_type=%s)",
            resolved_delivery_id,
            type(exc).__name__,
        )
        return WebhookDeliveryResult(
            False, resolved_delivery_id, error="transport_error"
        )


def _has_safe_url_shape(webhook_url: str) -> bool:
    return _parse_safe_webhook_url(webhook_url) is not None


def _parse_safe_webhook_url(webhook_url: str) -> Optional[httpx.URL]:
    """Parse once with HTTPX and enforce the URL policy used for delivery."""
    if (
        not webhook_url
        or len(webhook_url) > MAX_WEBHOOK_URL_LENGTH
        or webhook_url != webhook_url.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in webhook_url)
    ):
        return None
    try:
        parsed = httpx.URL(webhook_url)
    except (httpx.InvalidURL, UnicodeError, ValueError):
        return None
    if (
        parsed.scheme != "https"
        or not parsed.raw_host
        or parsed.userinfo
        or parsed.fragment
        or parsed.port not in (None, HTTPS_PORT)
    ):
        return None

    hostname = parsed.host.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        return None
    try:
        if not _is_public_unicast(ipaddress.ip_address(hostname)):
            return None
    except ValueError:
        pass
    return parsed


def _is_public_unicast(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is globally routable unicast.

    Older Python ``ipaddress`` releases classify multicast and several
    transition/special ranges as global.  Reject those explicitly so library
    version differences cannot weaken the SSRF boundary.
    """
    if (
        not address.is_global
        or address.is_multicast
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_reserved
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.is_site_local:
        return False
    if any(
        address.version == network.version and address in network
        for network in _EXTRA_NON_PUBLIC_NETWORKS
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and (
        address.ipv4_mapped is not None
        or address.sixtofour is not None
        or address.teredo is not None
    ):
        return False
    return True


async def _destination_is_public(webhook_url: str) -> bool:
    """Resolve the destination and require every address to be globally routable."""
    return bool(await _resolve_public_addresses(webhook_url))


async def _resolve_hostname(hostname: str) -> list[tuple[Any, ...]]:
    """Resolve on an isolated, bounded executor so stalls cannot block app I/O."""
    return await _resolve_hostname_with(
        hostname,
        executor=_DNS_EXECUTOR,
        admission=_DNS_ADMISSION,
    )


async def _resolve_config_hostname(hostname: str) -> list[tuple[Any, ...]]:
    """Resolve Settings validation separately from delivery-critical DNS work."""
    return await _resolve_hostname_with(
        hostname,
        executor=_CONFIG_DNS_EXECUTOR,
        admission=_CONFIG_DNS_ADMISSION,
    )


async def _resolve_hostname_with(
    hostname: str,
    *,
    executor: ThreadPoolExecutor,
    admission: asyncio.Semaphore,
) -> list[tuple[Any, ...]]:
    """Resolve with bounded admission and retain a slot until the worker exits."""
    loop = asyncio.get_running_loop()

    async def _submit_and_wait() -> list[tuple[Any, ...]]:
        await admission.acquire()
        try:
            future = loop.run_in_executor(
                executor,
                socket.getaddrinfo,
                hostname,
                HTTPS_PORT,
                0,
                socket.SOCK_STREAM,
            )
        except BaseException:
            admission.release()
            raise
        # A timed-out getaddrinfo call cannot be cancelled. Keep its admission
        # slot until the worker really exits so executor submissions stay bounded.
        future.add_done_callback(lambda _future: admission.release())
        return await asyncio.shield(future)

    return await asyncio.wait_for(_submit_and_wait(), timeout=DNS_TIMEOUT_SECONDS)


async def _resolve_public_addresses(
    webhook_url: str,
    *,
    resolver=None,
) -> Optional[tuple[str, ...]]:
    """Return the exact public addresses a delivery may connect to."""
    parsed = _parse_safe_webhook_url(webhook_url)
    if parsed is None:
        return None
    hostname = parsed.host
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        return (str(literal),) if _is_public_unicast(literal) else None

    try:
        records = await (resolver or _resolve_hostname)(hostname)
    except (asyncio.TimeoutError, OSError, UnicodeError, ValueError):
        return None

    addresses: list[str] = []
    seen: set[str] = set()
    for record in records:
        try:
            address = ipaddress.ip_address(record[4][0])
        except (IndexError, ValueError):
            return None
        if not _is_public_unicast(address):
            return None
        normalized = str(address)
        if normalized not in seen:
            seen.add(normalized)
            addresses.append(normalized)
    return tuple(addresses) or None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
