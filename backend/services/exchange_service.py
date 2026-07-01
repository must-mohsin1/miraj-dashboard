"""CCXT exchange service — reads encrypted API keys from the DB, configures a
ccxt exchange instance, and fetches portfolio data (balances, positions, trades).

Usage::

    from backend.services.exchange_service import get_exchange, fetch_portfolio

    exchange = await get_exchange(user_id=42, exchange_name="mexc", db_session=session)
    data = await fetch_portfolio(exchange_instance=exchange, user_id=42)
    # data == {"balances": [...], "positions": [...], "trades": [...]}

Error handling
--------------
ccxt exceptions are translated to custom :class:`ExchangeError` subclasses
that the route layer maps to HTTP status codes:

* :class:`ExchangeAuthError`       → HTTP 400 (connect) or 502 (refresh)
* :class:`ExchangeRateLimitError`  → HTTP 429
* :class:`ExchangeTimeoutError`    → HTTP 502
* :class:`ExchangeError`          → HTTP 502

Designed for multi-exchange from day one: adding Binance means one entry in
:data:`SUPPORTED_EXCHANGES` (loaded lazily from ccxt).

.. important::

   Never log or print key material.  This service handles plaintext API keys
   in memory only — they are encrypted before storage by the route layer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ExchangeKey
from backend.services.encryption import decrypt_api_key

logger = logging.getLogger(__name__)

# ── Custom exceptions ────────────────────────────────────────────────────────


class ExchangeError(Exception):
    """Base exception for all exchange service errors."""

    code = "exchange_error"


class ExchangeAuthError(ExchangeError):
    """API key is invalid, revoked, or has insufficient permissions."""

    code = "authentication_error"


class ExchangeRateLimitError(ExchangeError):
    """The exchange rate-limited a request (HTTP 429)."""

    code = "rate_limit_error"


class ExchangeTimeoutError(ExchangeError):
    """A request to the exchange timed out."""

    code = "timeout_error"


# ── Configuration ────────────────────────────────────────────────────────────

#: Timeout (ms) for individual ccxt API calls.
REQUEST_TIMEOUT_MS = 15_000

#: Overall deadline (seconds) for a full portfolio fetch.
PORTFOLIO_FETCH_TIMEOUT_S = 30.0


# ── Supported exchanges  (add one line per new exchange — no other code changes)
# ---------------------------------------------------------------------------

#: Dict mapping exchange slug → ccxt exchange class.
#: Populated lazily on first use so importing this module doesn't pull in ccxt.
SUPPORTED_EXCHANGES: Dict[str, type] = {}
_exchanges_loaded = False


def _load_supported_exchanges() -> None:
    """Import ccxt and populate :data:`SUPPORTED_EXCHANGES` (idempotent)."""
    global _exchanges_loaded
    if _exchanges_loaded:
        return
    import ccxt  # noqa: PLC0415 — lazy import (ccxt is a large library)

    SUPPORTED_EXCHANGES["mexc"] = ccxt.mexc
    _exchanges_loaded = True


def is_ccxt_available() -> bool:
    """Return ``True`` if the ``ccxt`` package is importable."""
    try:
        import ccxt  # noqa: PLC0415

        return True
    except ImportError:
        return False


def get_supported_exchanges() -> Dict[str, type]:
    """Return the supported-exchanges dict, loading ccxt on first call."""
    _load_supported_exchanges()
    return SUPPORTED_EXCHANGES


# ── Error translation ───────────────────────────────────────────────────────


def _translate_ccxt_error(exc: Exception) -> ExchangeError:
    """Translate a raw ccxt exception into an :class:`ExchangeError` subclass.

    If *exc* is already one of our custom types, it is returned as-is.
    """
    if isinstance(exc, ExchangeError):
        return exc

    try:
        import ccxt  # noqa: PLC0415
    except ImportError:
        return ExchangeError(f"ccxt not available: {exc}")

    if isinstance(exc, ccxt.AuthenticationError):
        return ExchangeAuthError(f"Invalid or revoked API credentials: {exc}")
    if isinstance(exc, ccxt.RateLimitExceeded):
        return ExchangeRateLimitError(
            "Rate limited by exchange — please try again in a few seconds"
        )
    if isinstance(exc, (ccxt.RequestTimeout, ccxt.NetworkError)):
        return ExchangeTimeoutError(
            f"Request to exchange timed out or network error: {exc}"
        )
    return ExchangeError(f"Unexpected exchange error: {exc}")


# ── Exchange instance helpers ──────────────────────────────────────────────


def create_exchange_instance(
    exchange_name: str,
    api_key: str,
    api_secret: str,
) -> Any:
    """Create a configured ccxt exchange instance from raw credentials.

    Does **not** read from the database — used by the connect endpoint to
    validate keys before storing them.

    Raises ``ValueError`` if the exchange is not in :data:`SUPPORTED_EXCHANGES`.
    """
    _load_supported_exchanges()
    exchange_name = exchange_name.lower()
    if exchange_name not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"Unsupported exchange '{exchange_name}'. "
            f"Supported: {list(SUPPORTED_EXCHANGES)}"
        )
    exchange_class = SUPPORTED_EXCHANGES[exchange_name]
    return exchange_class({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "timeout": REQUEST_TIMEOUT_MS,
    })


def validate_exchange_keys(exchange_instance: Any) -> None:
    """Validate API credentials by calling ``fetchBalance()``.

    Raises an :class:`ExchangeError` subclass on failure.
    """
    try:
        exchange_instance.fetchBalance()
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc


# ── Public API ───────────────────────────────────────────────────────────────


async def get_exchange(
    user_id: int,
    exchange_name: str,
    db_session: AsyncSession,
) -> Any:
    """Read the user's encrypted API credentials for *exchange_name* from the
    DB, decrypt them, and return a configured ccxt exchange instance.

    Parameters
    ----------
    user_id:
        The user's primary key.
    exchange_name:
        Exchange slug (e.g. ``"mexc"``, ``"binance"``). Case-insensitive.
    db_session:
        An open async SQLAlchemy session.

    Returns
    -------
    Any
        A configured ccxt exchange instance ready to call market/trade methods.

    Raises
    ------
    ValueError
        If the exchange is not supported or if no API keys exist for this
        user + exchange.
    """
    _load_supported_exchanges()
    exchange_name = exchange_name.lower()
    if exchange_name not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"Unsupported exchange '{exchange_name}'. "
            f"Supported: {list(SUPPORTED_EXCHANGES)}"
        )

    result = await db_session.execute(
        select(ExchangeKey).where(
            ExchangeKey.user_id == user_id,
            ExchangeKey.exchange == exchange_name,
        )
    )
    key_row = result.scalar_one_or_none()
    if key_row is None:
        raise ValueError(
            f"No API keys found for user {user_id} on exchange '{exchange_name}'."
        )

    api_key = decrypt_api_key(key_row.api_key_encrypted)
    api_secret = decrypt_api_key(key_row.api_secret_encrypted)

    exchange_class = SUPPORTED_EXCHANGES[exchange_name]
    return exchange_class({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "timeout": REQUEST_TIMEOUT_MS,
    })


async def fetch_portfolio(
    exchange_instance: Any,
    user_id: int,
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch spot balances, futures positions, and recent trades.

    Runs all three blocking ccxt calls in a thread pool with a 30 s overall
    deadline.

    Returns ``{"balances": [...], "positions": [...], "trades": [...]}`` where
    each list element is a dict shaped to match the corresponding ORM model
    columns for direct insert.

    Raises :class:`ExchangeAuthError`, :class:`ExchangeRateLimitError`,
    :class:`ExchangeTimeoutError`, or :class:`ExchangeError` on failure.
    """
    exchange_name = exchange_instance.id  # e.g. "mexc"

    try:
        # Fetch balances first, then trades (trades need balance symbols)
        balances = await asyncio.to_thread(
            _fetch_balances, exchange_instance, user_id, exchange_name
        )
        positions, trades = await asyncio.gather(
            asyncio.to_thread(
                _fetch_positions, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_trades, exchange_instance, user_id, exchange_name, balances
            ),
        )
    except asyncio.TimeoutError:
        raise ExchangeTimeoutError(
            f"Portfolio fetch exceeded {PORTFOLIO_FETCH_TIMEOUT_S}s timeout"
        ) from None
    except ExchangeError:
        raise
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc

    return {"balances": balances, "positions": positions, "trades": trades}


# ── Internal fetch helpers (blocking — called via asyncio.to_thread) ─────────


def _fetch_balances(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> List[Dict[str, Any]]:
    """Fetch spot balances from the exchange, filtering out dust.

    Dust assets (``free + locked < 1e-8``) are omitted before the result is
    returned so that the DB is not bloated with zero-balance rows.
    """
    try:
        raw = exchange.fetchBalance()
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc

    result: List[Dict[str, Any]] = []

    for currency, data in raw.items():
        if not isinstance(data, dict) or "free" not in data:
            # Skip non-balance entries: "info", "free", "used", "total" keys
            # are top-level in the ccxt balance response (summary dicts, not
            # per-currency balance dicts).
            continue

        free = float(data.get("free", 0) or 0)
        locked = float(data.get("used", 0) or 0)
        total = float(data.get("total", free + locked) or 0)

        # Dust filter — skip assets with effectively zero balance
        if free + locked < 1e-8:
            continue

        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "asset": currency,
            "free": free,
            "locked": locked,
            "total": total,
        })

    return result


def _fetch_positions(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> List[Dict[str, Any]]:
    """Fetch open futures positions.

    Spot-only accounts raise ``BadSymbol`` or ``NotSupported`` — both are
    caught and return an empty list.
    """
    import ccxt  # noqa: PLC0415

    try:
        raw = exchange.fetchPositions()
    except (ccxt.BadSymbol, ccxt.NotSupported):
        return []
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc

    result: List[Dict[str, Any]] = []
    for pos in raw:
        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "symbol": (pos.get("symbol") or "").replace("/", ""),
            "side": pos.get("side", "long"),
            "size": float(pos.get("contracts", pos.get("size", 0)) or 0),
            "entry_price": float(pos.get("entryPrice", 0) or 0),
            "mark_price": float(pos.get("markPrice", 0) or 0),
            "pnl": float(pos.get("unrealizedPnl", pos.get("pnl", 0)) or 0),
            "pnl_percent": float(pos.get("percentage", 0) or 0),
            "leverage": float(pos.get("leverage", 1) or 1),
            "liquidation_price": _safe_float(pos.get("liquidationPrice")),
            "margin": float(pos.get("collateral", pos.get("margin", 0)) or 0),
        })

    return result


def _fetch_trades(
    exchange: Any,
    user_id: int,
    exchange_name: str,
    balances: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Fetch recent trades across the user's active symbols.

    MEXC requires a symbol argument for fetchMyTrades (symbolRequired=True).
    We iterate over the user's non-dust balance assets, construct USDT pairs,
    and fetch a small number of trades per symbol.
    """
    result: List[Dict[str, Any]] = []

    # Build list of symbols to query from balances
    symbols_to_query: List[str] = []
    if balances:
        for bal in balances:
            asset = bal.get("asset", "").upper()
            if not asset or asset in ("USDT", "USD", "USDC", "BUSD", "TUSD"):
                continue
            # Try USDT pair
            symbols_to_query.append(f"{asset}/USDT")

    # If no balances yielded symbols, return empty — no trades to fetch
    if not symbols_to_query:
        return result

    # Limit to top 10 symbols to avoid rate limits
    symbols_to_query = symbols_to_query[:10]

    all_trades: List[dict] = []
    for symbol in symbols_to_query:
        try:
            raw = exchange.fetchMyTrades(symbol=symbol, limit=10)
            all_trades.extend(raw)
        except Exception:
            # Skip symbols that fail (delisted, no trades, etc.)
            continue

    # Sort all trades by timestamp descending and keep top 50
    all_trades.sort(key=lambda t: t.get("timestamp", 0) or 0, reverse=True)
    all_trades = all_trades[:50]

    for trade in all_trades:
        fee_info = trade.get("fee") or {}
        ts = trade.get("timestamp")
        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "symbol": (trade.get("symbol") or "").replace("/", ""),
            "side": trade.get("side", ""),
            "type": trade.get("takerOrMaker", "market"),
            "price": float(trade.get("price", 0) or 0),
            "amount": float(trade.get("amount", 0) or 0),
            "cost": float(trade.get("cost", 0) or 0),
            "fee": _safe_float(fee_info.get("cost")),
            "fee_currency": fee_info.get("currency"),
            "timestamp": (
                datetime.utcfromtimestamp(ts / 1000.0)
                if ts else datetime.utcnow()
            ),
            "exchange_trade_id": str(trade.get("id", "")),
        })

    return result


# ── Low-level helpers ────────────────────────────────────────────────────────


def _safe_float(value: Any) -> Optional[float]:
    """Convert *value* to float, or return ``None`` if it's None/missing."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
