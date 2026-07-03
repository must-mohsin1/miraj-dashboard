"""SSE streaming endpoint for live prices.

GET /api/v1/stream/prices?symbols=BTC-USD,ETH-USD
    Returns a Server-Sent Events stream: data: {"symbol":"BTC-USD","price":62000,"timestamp":1234567890}
    Uses ccxt fetchTicker for each symbol every 5 seconds.
    Requires JWT auth (Bearer header or ?token= query param).

The query-param auth path exists because the browser ``EventSource`` API
cannot set custom headers, so the frontend passes the JWT as
``?token=<jwt>``.  The standard ``Authorization: Bearer`` header (handled
by :func:`backend.auth.get_current_user`) is also accepted for
non-EventSource clients (``curl``, fetch-based readers).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from backend.auth import decode_access_token
from backend.database import get_session_factory
from backend.models import User, WatchlistPair
from backend.services.exchange_service import _translate_ccxt_error

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["stream"])

#: Interval (seconds) between price polls for each symbol.
POLL_INTERVAL_SECONDS = 5

#: Maximum number of symbols a single SSE connection may subscribe to.
MAX_SYMBOLS = 25


# ── Symbol normalisation ───────────────────────────────────────────────────


def _to_ccxt_symbol(symbol: str) -> str:
    """Translate a dashboard symbol into a ccxt market symbol.

    The app uses three symbol conventions depending on the surface:
      * Yahoo Finance (analysis page): ``BTC-USD``
      * Watchlist / exchange pairs:      ``BTCUSDT``
      * ccxt unified:                    ``BTC/USD`` or ``BTC/USDT``

    For live streaming we prefer ``/USDT`` pairs on Binance because they
    have the highest liquidity and most frequent price updates.
    ``BTC-USD`` → ``BTC/USDT``, ``ETH-USD`` → ``ETH/USDT``.
    """
    s = symbol.strip().upper()
    if "/" in s:
        return s

    # Yahoo-finance style: BTC-USD, ETH-USD
    if "-" in s:
        base, quote = s.split("-", 1)
        # Convert -USD suffix to /USDT for better liquidity on Binance
        if quote == "USD":
            return f"{base}/USDT"
        return f"{base}/{quote}"

    # Bare concatenated form: BTCUSDT, ETHUSDT
    for quote in ("USDT", "USDC", "BUSD", "TUSD", "FDUSD", "USD", "BTC", "ETH"):
        if s.endswith(quote) and len(s) > len(quote):
            base = s[: -len(quote)]
            if base:
                return f"{base}/{quote}"

    # Fallback: assume /USDT
    return f"{s}/USDT"


def _display_symbol(symbol: str) -> str:
    """Return the symbol in the caller's original casing (for SSE payload)."""
    return symbol.strip().upper()


# ── Lightweight ccxt exchange for public ticker reads ──────────────────────

_ccxt_exchange: Any = None
_ccxt_exchange_lock = asyncio.Lock()


async def _get_public_exchange() -> Any:
    """Return a singleton ccxt exchange instance for public ticker reads.

    We use Binance's public endpoint (no API key required) for ticker
    polling — it supports all major spot pairs and has generous public
    rate limits.  Falls back to creating a bare ccxt exchange on first use.
    """
    global _ccxt_exchange
    if _ccxt_exchange is not None:
        return _ccxt_exchange

    async with _ccxt_exchange_lock:
        if _ccxt_exchange is not None:
            return _ccxt_exchange

        import ccxt  # noqa: PLC0415

        ex = ccxt.binance({"enableRateLimit": True, "timeout": 10_000})
        _ccxt_exchange = ex
        return ex


async def _fetch_ticker_price(exchange: Any, ccxt_symbol: str) -> Optional[float]:
    """Fetch the latest price for a single ccxt symbol.

    Runs the blocking ``fetchTicker`` in a thread pool.  Returns ``None``
    on error (so a single bad symbol doesn't kill the whole stream).

    Note: ccxt caches ticker responses internally.  We clear the cache
    before each fetch to ensure we always get the latest price.
    """
    try:
        ticker = await asyncio.to_thread(exchange.fetchTicker, ccxt_symbol)
        if ticker and ticker.get("last") is not None:
            return float(ticker["last"])
        if ticker and ticker.get("close") is not None:
            return float(ticker["close"])
        return None
    except Exception as exc:
        translated = _translate_ccxt_error(exc)
        logger.debug("fetchTicker failed for %s: %s", ccxt_symbol, translated)
        return None


# ── Token-from-query helper ────────────────────────────────────────────────


async def _extract_token(request: Request, token_query: Optional[str]) -> str:
    """Extract the JWT from a Bearer header or ``?token=`` query param."""
    # Prefer the Authorization header when present (the standard path).
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    # Fall back to the query param (EventSource cannot set headers).
    if token_query:
        return token_query
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _get_user_from_query_or_header(
    request: Request,
    token_query: Optional[str],
) -> User:
    """Resolve the authenticated user from a query-param token or Bearer header.

    EventSource can't set headers, so the frontend passes the JWT as
    ``?token=<jwt>``.  We reconstruct the same credential flow that
    :func:`get_current_user` uses.
    """
    jwt_token = await _extract_token(request, token_query)
    payload = decode_access_token(jwt_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    factory = get_session_factory()
    async with factory() as session:
        user = await session.get(User, int(user_id_str))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user


async def _filter_watchlist_symbols(
    user_id: int, symbols: list[str]
) -> list[str]:
    """Return only the symbols that are in the user's watchlist.

    If the user has no watchlist pairs at all (empty watchlist), we permit
    all requested symbols — this keeps the feature usable for brand-new
    users who haven't added pairs yet.  Otherwise we bound resource use by
    only streaming pairs the user explicitly watchlisted.
    """
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(WatchlistPair.pair).where(WatchlistPair.user_id == user_id)
        )
        rows = list(result.scalars().all())

    # Empty watchlist → allow all (don't block a brand-new user)
    if not rows:
        return symbols

    # Build a set of normalised watchlist pairs for fast lookup.
    # Watchlist pairs are stored in various formats (BTCUSDT, BTC-USD, BTC/USDT)
    # so we normalise by stripping separators.
    def _norm(s: str) -> str:
        return s.strip().upper().replace("/", "").replace("-", "")

    allowed = {_norm(p) for p in rows}
    return [s for s in symbols if _norm(s) in allowed]


# ── SSE generator ──────────────────────────────────────────────────────────


async def _price_stream(
    symbols: list[str],
    disconnected: asyncio.Event,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted price updates every ``POLL_INTERVAL_SECONDS``.

    Stops when *disconnected* is set (client closed the connection).
    """
    display_map = {s: _display_symbol(s) for s in symbols}
    ccxt_map = {s: _to_ccxt_symbol(s) for s in symbols}

    exchange = await _get_public_exchange()

    # Send an initial comment so the browser knows the stream is alive
    yield ": connected\n\n"

    while not disconnected.is_set():
        # Fetch all symbols concurrently
        async def _one(sym: str) -> Optional[tuple[str, float, int]]:
            price = await _fetch_ticker_price(exchange, ccxt_map[sym])
            if price is None:
                return None
            return (display_map[sym], price, int(time.time()))

        results = await asyncio.gather(*[_one(s) for s in symbols], return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                logger.debug("price stream error: %s", r)
                continue
            if r is None:
                continue
            sym, price, ts = r
            payload = json.dumps(
                {"symbol": sym, "price": price, "timestamp": ts},
                separators=(",", ":"),
            )
            yield f"data: {payload}\n\n"

        # Wait for the next interval (cancellable on disconnect)
        try:
            await asyncio.wait_for(disconnected.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


# ── Route ─────────────────────────────────────────────────────────────────


@router.get("/stream/prices")
async def stream_prices(
    request: Request,
    symbols: str = Query(
        ...,
        description="Comma-separated trading pairs, e.g. BTC-USD,ETH-USD (max 25)",
    ),
    token: Optional[str] = Query(
        None,
        description="JWT access token (alternative to Authorization header for EventSource)",
    ),
):
    """Stream live prices as Server-Sent Events.

    Each event line is ``data: {"symbol":"BTC-USD","price":62000,"timestamp":1234567890}\\n\\n``.
    Polls each symbol via ccxt ``fetchTicker`` every 5 seconds.

    Auth: Bearer header **or** ``?token=<jwt>`` query param (EventSource can't
    set headers).
    """
    user = await _get_user_from_query_or_header(request, token)

    # Parse + validate symbol list
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No symbols provided",
        )
    if len(sym_list) > MAX_SYMBOLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many symbols (max {MAX_SYMBOLS})",
        )
    sym_list = [s.upper() for s in sym_list]

    # Filter to watchlist (bound resource use)
    sym_list = await _filter_watchlist_symbols(user.id, sym_list)
    if not sym_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the requested symbols are in your watchlist",
        )

    # Connection-state tracking for cleanup on disconnect
    disconnected = asyncio.Event()

    async def _on_disconnect() -> None:
        disconnected.set()

    # Detect client disconnect by polling request.is_disconnected().
    # That call returns a bool (not awaiting a future), so we poll it.
    async def _watch_disconnect() -> None:
        try:
            while not disconnected.is_set():
                is_disc = await request.is_disconnected()
                if is_disc:
                    break
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("disconnect watcher ended: %s", exc)
        finally:
            await _on_disconnect()

    # Spawn a background watcher that flips `disconnected` when the client closes.
    watch_task = asyncio.create_task(_watch_disconnect())

    async def _generator():
        try:
            async for chunk in _price_stream(sym_list, disconnected):
                yield chunk
        finally:
            await _on_disconnect()
            watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
