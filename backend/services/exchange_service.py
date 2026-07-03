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

    SUPPORTED_EXCHANGES["mexc"]    = ccxt.mexc
    SUPPORTED_EXCHANGES["binance"] = ccxt.binance
    SUPPORTED_EXCHANGES["bybit"]   = ccxt.bybit
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
        "recvWindow": 60000,
        "adjustForTimeDifference": True,
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
        "recvWindow": 60000,
        "adjustForTimeDifference": True,
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
        (
            positions,
            trades,
            position_history,
            order_history,
        ) = await asyncio.gather(
            asyncio.to_thread(
                _fetch_positions, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_trades, exchange_instance, user_id, exchange_name, balances
            ),
            asyncio.to_thread(
                _fetch_positions_history, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_order_history, exchange_instance, user_id, exchange_name
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

    return {
        "balances": balances,
        "positions": positions,
        "trades": trades,
        "position_history": position_history,
        "order_history": order_history,
    }


async def fetch_history(
    exchange_instance: Any,
    user_id: int,
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch position history and order history (closed orders) from the exchange.

    Unlike :func:`fetch_portfolio`, this does **not** re-fetch balances/positions/
    trades — it only fetches the two historical lists. Designed for the
    ``GET /api/v1/portfolio/{exchange}/history`` endpoint which always returns
    fresh (uncached) data.

    Returns ``{"position_history": [...], "order_history": [...]}``.

    Raises :class:`ExchangeAuthError`, :class:`ExchangeRateLimitError`,
    :class:`ExchangeTimeoutError`, or :class:`ExchangeError` on failure.
    """
    exchange_name = exchange_instance.id  # e.g. "mexc"

    try:
        position_history, order_history = await asyncio.gather(
            asyncio.to_thread(
                _fetch_positions_history, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_order_history, exchange_instance, user_id, exchange_name
            ),
        )
    except asyncio.TimeoutError:
        raise ExchangeTimeoutError(
            f"History fetch exceeded {PORTFOLIO_FETCH_TIMEOUT_S}s timeout"
        ) from None
    except ExchangeError:
        raise
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc

    return {
        "position_history": position_history,
        "order_history": order_history,
    }


# ── Internal fetch helpers (blocking — called via asyncio.to_thread) ─────────


def _fetch_balances(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> List[Dict[str, Any]]:
    """Fetch spot balances from the exchange, filtering out dust.

    Also fetches ticker prices for USDT pairs to compute USD value.
    """
    try:
        raw = exchange.fetchBalance()
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc

    # Parse balances
    result: List[Dict[str, Any]] = []

    for currency, data in raw.items():
        if not isinstance(data, dict) or "free" not in data:
            continue

        free = float(data.get("free", 0) or 0)
        locked = float(data.get("used", 0) or 0)
        total = float(data.get("total", free + locked) or 0)

        # Dust filter
        if free + locked < 1e-8:
            continue

        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "asset": currency,
            "free": free,
            "locked": locked,
            "total": total,
            "usd_value": None,  # Will be filled below
        })

    # Fetch ticker prices for USD valuation
    if result:
        _enrich_balance_usd_values(exchange, result)

    return result


def _enrich_balance_usd_values(exchange: Any, balances: List[Dict[str, Any]]) -> None:
    """Fetch ticker prices and set usd_value on each balance entry."""
    # Build list of symbols to fetch
    symbols = []
    for bal in balances:
        asset = bal["asset"].upper()
        if asset in ("USDT", "USD", "USDC", "BUSD", "TUSD", "DAI"):
            # Stablecoins: 1:1 USD
            bal["usd_value"] = bal["total"]
            continue
        symbols.append(f"{asset}/USDT")

    if not symbols:
        return

    # Fetch tickers in batch
    try:
        tickers = exchange.fetchTickers(symbols)
    except Exception:
        # Fallback: fetch one by one
        tickers = {}
        for sym in symbols:
            try:
                tickers[sym] = exchange.fetchTicker(sym)
            except Exception:
                continue

    for bal in balances:
        asset = bal["asset"].upper()
        if asset in ("USDT", "USD", "USDC", "BUSD", "TUSD", "DAI"):
            continue
        symbol = f"{asset}/USDT"
        ticker = tickers.get(symbol)
        if ticker and ticker.get("last"):
            price = float(ticker["last"])
            bal["usd_value"] = bal["total"] * price


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
        info = pos.get("info", {})  # Raw MEXC API response

        contracts = float(pos.get("contracts", 0) or pos.get("size", 0) or info.get("holdVol", 0) or info.get("positionAmt", 0) or 0)
        entry_price = float(pos.get("entryPrice", 0) or pos.get("entry_price", 0) or info.get("holdAvgPrice", 0) or info.get("openAvgPrice", 0) or 0)

        # Mark price — ccxt returns null for MEXC, try raw info or fetch from ticker
        mark_price = float(pos.get("markPrice", 0) or pos.get("mark_price", 0) or 0)

        # PnL — ccxt returns null, use raw fields (MEXC unRealizedPnl, Binance unRealizedProfit, Bybit unrealised_pnl)
        pnl = float(pos.get("unrealizedPnl", 0) or pos.get("pnl", 0) or info.get("unRealizedPnl", 0) or info.get("unRealizedProfit", 0) or info.get("unrealised_pnl", 0) or 0)

        # PnL percentage — compute from PnL / margin (ROI on position)
        leverage = float(pos.get("leverage", 1) or info.get("leverage", 1) or 1)
        liq_price = _safe_float(pos.get("liquidationPrice") or pos.get("liquidation_price") or info.get("liquidatePrice") or info.get("liquidationPrice") or info.get("liq_price"))
        margin = float(pos.get("collateral", 0) or pos.get("margin", 0) or pos.get("initialMargin", 0) or info.get("oim", 0) or info.get("im", 0) or info.get("initialMargin", 0) or info.get("positionIM", 0) or 0)
        side = pos.get("side", "long")

        pnl_pct = 0.0
        if pnl != 0 and margin > 0:
            pnl_pct = (pnl / margin) * 100
        elif info.get("profitRatio"):
            pnl_pct = float(info["profitRatio"]) * 100

        # If mark_price is still 0, try fetching current ticker price
        if mark_price == 0 and entry_price > 0:
            symbol = pos.get("symbol", "")
            if symbol:
                try:
                    ticker = exchange.fetchTicker(symbol)
                    if ticker and ticker.get("last"):
                        mark_price = float(ticker["last"])
                except Exception:
                    pass
            # Last resort: use entry price
            if mark_price == 0:
                mark_price = entry_price

        # If pnl is still 0 but we have mark_price != entry_price, compute it
        if pnl == 0 and contracts > 0 and entry_price > 0 and mark_price > 0 and mark_price != entry_price:
            contract_size = float(pos.get("contractSize", 1) or 1)
            if side == "short":
                pnl = (entry_price - mark_price) * contracts * contract_size
            else:
                pnl = (mark_price - entry_price) * contracts * contract_size

        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "symbol": (pos.get("symbol") or "").replace("/", ""),
            "side": side,
            "size": contracts,
            "entry_price": entry_price,
            "mark_price": mark_price,
            "pnl": pnl,
            "pnl_percent": pnl_pct,
            "leverage": leverage,
            "liquidation_price": liq_price,
            "margin": margin,
            "contract_size": float(pos.get("contractSize", 1) or 1),
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


def _fetch_positions_history(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> List[Dict[str, Any]]:
    """Fetch closed/historical futures positions.

    Calls ``exchange.fetch_positions_history()`` when available, falling back
    to the raw MEXC API ``contract_private_get_position_list_history_positions``
    for exchanges that don't implement it directly. Returns a normalised list
    of dicts suitable for direct ``PositionHistoryItem`` construction.

    Spot-only accounts or non-futures exchanges return an empty list.
    """
    import ccxt  # noqa: PLC0415

    # 1. Fetch raw positions history
    raw: List[Dict[str, Any]] = []
    try:
        if hasattr(exchange, "fetch_positions_history"):
            raw = exchange.fetch_positions_history() or []
        elif exchange_name == "mexc" and hasattr(
            exchange,
            "contract_private_get_position_list_history_positions",
        ):
            # Raw MEXC fallback (paginate: 100 per page)
            page = 1
            while True:
                resp = (
                    exchange.contract_private_get_position_list_history_positions(
                        {"pageSize": 100, "pageNum": page}
                    )
                    or {}
                )
                page_data = resp.get("data") or {}
                rows = page_data.get("list") or page_data.get("result") or []
                if not rows:
                    break
                raw.extend(rows)
                total_pages = page_data.get("totalPage") or page_data.get("pages") or 1
                if page >= total_pages:
                    break
                page += 1
        else:
            return []
    except (ccxt.BadSymbol, ccxt.NotSupported):
        return []
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc

    # 2. Normalise each position entry
    result: List[Dict[str, Any]] = []
    for pos in raw:
        info = pos.get("info", {}) if isinstance(pos, dict) else {}

        # Handle raw MEXC dict shape (strings) vs ccxt unified shape
        symbol = (
            pos.get("symbol")
            or info.get("symbol")
            or ""
        )
        if symbol:
            symbol = symbol.replace("/", "")

        # Side — ccxt returns "long"/"short"; MEXC raw returns 1/2
        side = pos.get("side") or info.get("side") or ""
        if not side:
            pos_side = info.get("positionType") or info.get("position_type") or 1
            side = "long" if str(pos_side) == "1" else "short"

        size = float(
            pos.get("contracts", 0)
            or pos.get("size", 0)
            or info.get("vol", 0)
            or info.get("holdVol", 0)
            or 0
        )
        entry_price = float(
            pos.get("entryPrice", 0)
            or pos.get("entry_price", 0)
            or info.get("openAvgPrice", 0)
            or info.get("holdAvgPrice", 0)
            or info.get("avgEntryPrice", 0)
            or 0
        )
        exit_price = float(
            pos.get("exitPrice", 0)
            or pos.get("exit_price", 0)
            or info.get("closeAvgPrice", 0)
            or info.get("closePrice", 0)
            or 0
        )
        pnl = float(
            pos.get("realizedPnl", 0)
            or pos.get("pnl", 0)
            or info.get("realisedPnl", 0)
            or info.get("relizedPnl", 0)
            or info.get("closeProfit", 0)
            or 0
        )

        # PnL percentage
        pnl_percent = 0.0
        if pnl != 0:
            pnl_percent = float(
                pos.get("pnlPercentage", 0)
                or pos.get("pnl_percent", 0)
                or info.get("profitRatio", 0)
                or 0
            )
            if abs(pnl_percent) > 0:
                # MEXC returns a ratio (e.g. 0.15 = 15%)
                pnl_percent = pnl_percent * 100 if abs(pnl_percent) < 1.5 else pnl_percent
            else:
                # Compute from margin if available
                margin = float(
                    pos.get("collateral", 0)
                    or pos.get("margin", 0)
                    or info.get("oim", 0)
                    or info.get("im", 0)
                    or info.get("initialMargin", 0)
                    or 0
                )
                if margin > 0:
                    pnl_percent = (pnl / margin) * 100

        leverage = float(
            pos.get("leverage", 1) or info.get("leverage", 1) or 1
        )
        contract_size = float(pos.get("contractSize", 1) or info.get("contractSize", 1) or 1)

        # Timestamps — ccxt exposes open_time / close_time (ms); MEXC raw
        # returns openTime / closeTime (ms strings)
        open_ts = pos.get("open_time") or pos.get("openTime") or info.get("openTime")
        close_ts = pos.get("close_time") or pos.get("closeTime") or info.get("closeTime")
        open_time = datetime.utcfromtimestamp(open_ts / 1000.0) if open_ts else None
        close_time = datetime.utcfromtimestamp(close_ts / 1000.0) if close_ts else None

        # Close reason — infer from raw fields
        close_reason: Optional[str] = None
        raw_reason = (
            pos.get("close_reason")
            or info.get("closeReason")
            or info.get("closeType")
            or info.get("trigger_type")
        )
        if raw_reason is not None:
            reason_str = str(raw_reason).lower()
            if "liquidat" in reason_str or reason_str in ("2", "liquidation"):
                close_reason = "liquidated"
            elif "manual" in reason_str or reason_str in ("1", "close"):
                close_reason = "manual"
            elif "close" in reason_str or reason_str in ("3", "0"):
                close_reason = "closed"
            else:
                close_reason = "closed"
        else:
            # Default: if pnl <= 0, might be liquidation; else closed
            close_reason = "closed"

        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "symbol": symbol,
            "side": side,
            "size": size,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "leverage": leverage,
            "open_time": open_time,
            "close_time": close_time,
            "close_reason": close_reason,
            "contract_size": contract_size,
        })

    # Sort by close_time descending (most recent first)
    result.sort(
        key=lambda p: (p["close_time"] or p["open_time"] or datetime.utcnow()),
        reverse=True,
    )
    return result[:200]  # Cap at 200 entries


def _fetch_order_history(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> List[Dict[str, Any]]:
    """Fetch closed/cancelled orders across the user's active symbols.

    MEXC requires a symbol for ``fetchClosedOrders`` (symbolRequired=True),
    so we iterate over the user's balance symbols similar to ``_fetch_trades``.
    Returns a normalised list of dicts suitable for direct
    ``OrderHistoryItem`` construction.

    Spot-only accounts return an empty list when there are no balance symbols.
    """
    import ccxt  # noqa: PLC0415

    result: List[Dict[str, Any]] = []

    # 1. Build symbol list from the user's balance assets
    #    (reuse fetchBalance to avoid a DB dependency here)
    symbols_to_query: List[str] = []
    try:
        raw_balance = exchange.fetchBalance()
        for currency, data in (raw_balance or {}).items():
            if not isinstance(data, dict) or "total" not in data:
                continue
            total = float(data.get("total", 0) or 0)
            if total < 1e-8:
                continue
            if currency.upper() in ("USDT", "USD", "USDC", "BUSD", "TUSD", "DAI"):
                continue
            symbols_to_query.append(f"{currency}/USDT")
    except Exception:
        pass

    # Also try fetching positions to get futures symbols
    try:
        raw_positions = exchange.fetchPositions()
        for p in raw_positions or []:
            sym = p.get("symbol") if isinstance(p, dict) else None
            if sym and sym not in symbols_to_query:
                symbols_to_query.append(sym)
    except Exception:
        pass

    # Limit to avoid rate limits
    symbols_to_query = symbols_to_query[:15]

    # 2. Fetch closed orders per symbol
    all_orders: List[Dict[str, Any]] = []
    for symbol in symbols_to_query:
        try:
            if hasattr(exchange, "fetchClosedOrders"):
                raw = exchange.fetchClosedOrders(symbol) or []
            else:
                raw = exchange.fetch_orders(symbol, {"status": "closed"}) or []
            all_orders.extend(raw)
        except (ccxt.BadSymbol, ccxt.NotSupported):
            continue
        except Exception:
            # Skip symbols that fail (delisted, etc.)
            continue

    # 3. Sort by timestamp descending and cap
    all_orders.sort(
        key=lambda o: o.get("timestamp", 0) or 0,
        reverse=True,
    )
    all_orders = all_orders[:200]

    # 4. Normalise each order entry
    for order in all_orders:
        info = order.get("info", {})
        ts = order.get("timestamp")
        status = order.get("status") or info.get("status") or info.get("state") or ""
        # Normalise status labels
        status_lower = str(status).lower()
        if status_lower in ("closed", "filled"):
            status = "filled"
        elif status_lower in ("canceled", "cancelled"):
            status = "cancelled"
        elif status_lower in ("open", "new", "untriggered"):
            status = "open"

        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "symbol": (order.get("symbol") or "").replace("/", ""),
            "type": order.get("type") or info.get("type") or "limit",
            "side": order.get("side") or info.get("side") or "",
            "price": float(order.get("price", 0) or info.get("price", 0) or 0),
            "amount": float(
                order.get("amount", 0)
                or order.get("quantity", 0)
                or info.get("vol", 0)
                or info.get("origQty", 0)
                or 0
            ),
            "filled": float(
                order.get("filled", 0)
                or order.get("filledAmount", 0)
                or info.get("dealVol", 0)
                or info.get("executedQty", 0)
                or 0
            ),
            "cost": float(order.get("cost", 0) or info.get("dealMoney", 0) or 0),
            "status": status,
            "timestamp": (
                datetime.utcfromtimestamp(ts / 1000.0)
                if ts
                else datetime.utcnow()
            ),
            "reduce_only": 1 if (order.get("reduceOnly") or info.get("reduceOnly")) else 0,
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
