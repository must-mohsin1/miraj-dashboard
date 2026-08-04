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
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
) -> Dict[str, Any]:
    """Fetch spot balances, futures positions, recent trades, and Phase 2A/2B sync streams."""
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
            futures_account,
            funding,
            transfers,
            deposits,
            withdrawals,
        ) = await asyncio.gather(
            asyncio.to_thread(
                _fetch_positions, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_trades, exchange_instance, user_id, exchange_name, balances
            ),
            asyncio.to_thread(
                _fetch_positions_history_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_order_history_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_futures_account_assets_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_funding_history_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_futures_transfers_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_deposits_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_withdrawals_with_coverage, exchange_instance, user_id, exchange_name
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

    sync = {
        "positions_history": position_history[1],
        "orders_history": order_history[1],
        "futures_account_assets": futures_account[1],
        "funding": funding[1],
        "futures_transfers": transfers[1],
        "deposits": deposits[1],
        "withdrawals": withdrawals[1],
    }
    # Portfolio-level partial reflects core Phase 2A streams only; capital gaps
    # surface via capital-flow response + sync panel, not top-level partial.
    _core_phase2a = ("positions_history", "orders_history", "futures_account_assets")
    return {
        "balances": balances,
        "positions": positions,
        "trades": trades,
        "position_history": position_history[0],
        "order_history": order_history[0],
        "futures_account": futures_account[0],
        "funding": funding[0],
        "futures_transfers": transfers[0],
        "deposits": deposits[0],
        "withdrawals": withdrawals[0],
        "sync": sync,
        "partial": any(
            not sync[stream].get("complete", False)
            for stream in _core_phase2a
            if stream in sync
        ),
    }


async def fetch_history(
    exchange_instance: Any,
    user_id: int,
) -> Dict[str, Any]:
    """Fetch position/order history and Phase 2B capital-flow streams from the exchange."""
    exchange_name = exchange_instance.id  # e.g. "mexc"

    try:
        (
            position_history,
            order_history,
            funding,
            transfers,
            deposits,
            withdrawals,
        ) = await asyncio.gather(
            asyncio.to_thread(
                _fetch_positions_history_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_order_history_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_funding_history_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_futures_transfers_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_deposits_with_coverage, exchange_instance, user_id, exchange_name
            ),
            asyncio.to_thread(
                _fetch_withdrawals_with_coverage, exchange_instance, user_id, exchange_name
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

    sync = {
        "positions_history": position_history[1],
        "orders_history": order_history[1],
        "funding": funding[1],
        "futures_transfers": transfers[1],
        "deposits": deposits[1],
        "withdrawals": withdrawals[1],
    }
    # History partial: core Phase 2A streams only (capital gaps do not flip it).
    _core_phase2a = ("positions_history", "orders_history", "futures_account_assets")
    return {
        "position_history": position_history[0],
        "order_history": order_history[0],
        "funding": funding[0],
        "futures_transfers": transfers[0],
        "deposits": deposits[0],
        "withdrawals": withdrawals[0],
        "sync": sync,
        "partial": any(
            not sync[stream].get("complete", False)
            for stream in _core_phase2a
            if stream in sync
        ),
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

    Uses the raw MEXC API ``contract_private_get_position_list_history_positions``
    for MEXC (ccxt's ``fetch_positions_history`` does not correctly parse MEXC's
    fields). Returns a normalised list of dicts suitable for direct
    ``PositionHistoryItem`` construction.

    Spot-only accounts or non-futures exchanges return an empty list.
    """
    import ccxt  # noqa: PLC0415

    # ── 1. Only MEXC raw API is supported here ────────────────────────────
    if not (
        exchange_name == "mexc"
        and hasattr(
            exchange,
            "contract_private_get_position_list_history_positions",
        )
    ):
        return []

    # Ensure markets are loaded so we can look up contract sizes.
    try:
        if not getattr(exchange, "markets", None):
            exchange.load_markets()
    except Exception:
        pass
    markets = getattr(exchange, "markets", {}) or {}

    # ── 2. Fetch raw positions history (paginate: 100 per page) ────────────
    positions_raw: List[Dict[str, Any]] = []
    try:
        page = 1
        while True:
            resp = (
                exchange.contract_private_get_position_list_history_positions(
                    {"pageSize": 100, "pageNum": page}
                )
                or {}
            )
            page_data = resp.get("data")
            # MEXC API returns data as a list directly (not a dict with "list" key)
            if isinstance(page_data, list):
                rows = page_data
            elif isinstance(page_data, dict):
                rows = page_data.get("list") or page_data.get("result") or []
            else:
                rows = []
            if not rows:
                break
            positions_raw.extend(rows)
            total_pages = (page_data.get("totalPage") or page_data.get("pages") or 1) if isinstance(page_data, dict) else 1
            if page >= total_pages:
                break
            page += 1
    except (ccxt.BadSymbol, ccxt.NotSupported):
        return []
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc

    # ── 3. Normalise each MEXC raw position entry ───────────────────────────
    result: List[Dict[str, Any]] = []
    for raw in positions_raw:
        # positionType: "1" = long, "2" = short
        pos_type = str(raw.get("positionType", "1"))
        side = "long" if pos_type == "1" else "short"

        # Symbol: MEXC returns "SOL_USDT" → "SOLUSDT"
        symbol = str(raw.get("symbol", "")).replace("_", "")

        # Resolve contract size for this symbol from markets.
        contract_size = 1.0
        if symbol:
            # MEXC market keys may be "SOL/USDT:USDT" etc.
            market = markets.get(symbol) or markets.get(
                symbol[:-4] + "/" + symbol[-4:]
            )
            if market:
                try:
                    contract_size = float(market.get("contractSize", 1) or 1)
                except (ValueError, TypeError):
                    contract_size = 1.0

        # Timestamps: createTime = open, updateTime = close (ms)
        open_ts = raw.get("createTime")
        close_ts = raw.get("updateTime")
        open_time = (
            datetime.utcfromtimestamp(int(open_ts) / 1000.0) if open_ts else None
        )
        close_time = (
            datetime.utcfromtimestamp(int(close_ts) / 1000.0) if close_ts else None
        )

        # PnL percent: profitRatio is a ratio (e.g. 0.0582 = 5.82%)
        try:
            pnl_percent = float(raw.get("profitRatio", 0) or 0) * 100
        except (ValueError, TypeError):
            pnl_percent = 0.0

        # Close reason: state "3" = closed. MEXC does not expose an explicit
        # liquidation code on the history endpoint; do not infer liquidation
        # from ROI/profitRatio alone.
        close_reason = "closed"

        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "symbol": symbol,
            "side": side,
            "size": _safe_float(raw.get("closeVol")) or 0.0,
            "entry_price": _safe_float(raw.get("holdAvgPrice")) or 0.0,
            "exit_price": _safe_float(raw.get("closeAvgPrice")) or 0.0,
            "pnl": _safe_float(raw.get("closeProfitLoss")) or 0.0,
            "pnl_percent": pnl_percent,
            "leverage": _safe_float(raw.get("leverage")) or 1.0,
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
    return result


def _fetch_order_history(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> List[Dict[str, Any]]:
    """Fetch closed/cancelled orders via the raw MEXC API.

    Uses ``contract_private_get_order_list_history_orders`` (ccxt's
    ``fetchClosedOrders`` does not correctly parse MEXC's numeric ``side``
    field). Returns a normalised list of dicts suitable for direct
    ``OrderHistoryItem`` construction.

    Spot-only accounts or non-MEXC exchanges return an empty list.
    """
    import ccxt  # noqa: PLC0415

    # ── 1. Only MEXC raw API is supported here ────────────────────────────
    if not (
        exchange_name == "mexc"
        and hasattr(exchange, "contract_private_get_order_list_history_orders")
    ):
        return []

    # ── 2. Fetch raw order history (paginate: 100 per page) ───────────────
    orders_raw: List[Dict[str, Any]] = []
    try:
        page = 1
        while True:
            resp = (
                exchange.contract_private_get_order_list_history_orders(
                    {"pageSize": 100, "pageNum": page}
                )
                or {}
            )
            page_data = resp.get("data")
            if isinstance(page_data, list):
                rows = page_data
            elif isinstance(page_data, dict):
                rows = page_data.get("list") or page_data.get("result") or []
            else:
                rows = []
            if not rows:
                break
            orders_raw.extend(rows)
            total_pages = (page_data.get("totalPage") or page_data.get("pages") or 1) if isinstance(page_data, dict) else 1
            if page >= total_pages:
                break
            page += 1
    except (ccxt.BadSymbol, ccxt.NotSupported):
        return []
    except Exception as exc:
        raise _translate_ccxt_error(exc) from exc

    # ── 3. Sort by createTime descending ─────────────────────────────────
    def _ts(o: Dict[str, Any]) -> int:
        try:
            return int(o.get("createTime", 0) or 0)
        except (ValueError, TypeError):
            return 0

    orders_raw.sort(key=_ts, reverse=True)

    # ── 4. MEXC side encoding ──────────────────────────────────────────────
    #   "1" = open long  = buy   → side="buy",  side_action="Open Long"
    #   "2" = close long = sell  → side="sell", side_action="Close Long"
    #   "3" = open short = sell  → side="sell", side_action="Open Short"
    #   "4" = close short= buy   → side="buy",  side_action="Close Short"
    _side_map = {
        "1": ("buy", "Open Long"),
        "2": ("sell", "Close Long"),
        "3": ("sell", "Open Short"),
        "4": ("buy", "Close Short"),
    }
    # orderType: "1"=limit, "2"=market, "5"=post_only
    _type_map = {"1": "limit", "2": "market", "5": "post_only"}
    # state: "3"=filled, "4"=cancelled, "5"=partially_filled
    _state_map = {
        "3": "filled",
        "4": "cancelled",
        "5": "partially_filled",
    }

    # ── 5. Normalise each MEXC raw order entry ──────────────────────────────
    result: List[Dict[str, Any]] = []
    for raw in orders_raw:
        side_code = str(raw.get("side", ""))
        side, side_action = _side_map.get(side_code, ("", side_code))

        order_type_code = str(raw.get("orderType", ""))
        order_type = _type_map.get(order_type_code, order_type_code or "limit")

        state_code = str(raw.get("state", ""))
        status = _state_map.get(state_code, state_code or "")

        # openType: "1" = open new position, "2" = reduce-only
        open_type = str(raw.get("openType", ""))
        reduce_only = 1 if open_type == "2" else 0

        # Timestamp
        ts = raw.get("createTime")
        timestamp = (
            datetime.utcfromtimestamp(int(ts) / 1000.0) if ts else datetime.utcnow()
        )

        # cost = filled_price * filled (not orderMargin)
        filled = _safe_float(raw.get("dealVol")) or 0.0
        filled_price = _safe_float(raw.get("dealAvgPrice")) or 0.0
        cost = filled_price * filled

        # Symbol: MEXC returns "SOL_USDT" → "SOLUSDT"
        symbol = str(raw.get("symbol", "")).replace("_", "")

        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "symbol": symbol,
            "type": order_type,
            "side": side,
            "side_action": side_action,
            "price": _safe_float(raw.get("price")) or 0.0,
            "amount": _safe_float(raw.get("vol")) or 0.0,
            "filled": filled,
            "filled_price": filled_price,
            "cost": cost,
            "status": status,
            "timestamp": timestamp,
            "fee": _safe_float(raw.get("fee")) or 0.0,
            "fee_currency": raw.get("feeCurrency") or "USDT",
            "leverage": _safe_float(raw.get("leverage")) or 1.0,
            "reduce_only": reduce_only,
        })

    return result


# ── Phase 2A MEXC sync helpers ───────────────────────────────────────────────


def _fetch_positions_history_with_coverage(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not (exchange_name == "mexc" and hasattr(exchange, "contract_private_get_position_list_history_positions")):
        return [], _coverage("positions_history", rows=[], status="unavailable", complete=False, reason="stream_not_supported")
    rows, paging = _paginate_mexc_history(exchange.contract_private_get_position_list_history_positions, "positions_history")
    normalised = _normalise_mexc_position_rows(exchange, rows, user_id, exchange_name)
    return normalised, _coverage("positions_history", rows=normalised, **paging)


def _fetch_order_history_with_coverage(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not (exchange_name == "mexc" and hasattr(exchange, "contract_private_get_order_list_history_orders")):
        return [], _coverage("orders_history", rows=[], status="unavailable", complete=False, reason="stream_not_supported")
    rows, paging = _paginate_mexc_history(exchange.contract_private_get_order_list_history_orders, "orders_history")
    normalised = _normalise_mexc_order_rows(rows, user_id, exchange_name)
    return normalised, _coverage("orders_history", rows=normalised, **paging)


def _fetch_futures_account_assets_with_coverage(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    if not (exchange_name == "mexc" and hasattr(exchange, "contract_private_get_account_assets")):
        return None, _coverage("futures_account_assets", rows=[], status="unavailable", complete=False, reason="futures_account_snapshot_missing")
    resp = exchange.contract_private_get_account_assets({}) or {}
    err = _mexc_error(resp)
    if err:
        return None, _coverage("futures_account_assets", rows=[], status="error", complete=False, error_code=err[0], error_message=_redact_error(err[1]))
    data = resp.get("data") or []
    if isinstance(data, dict):
        data = [data]
    if not data:
        return None, _coverage("futures_account_assets", rows=[], status="unavailable", complete=False, reason="futures_account_snapshot_missing")
    raw = data[0]
    source_ts = _mexc_datetime(raw.get("updateTime") or raw.get("timestamp")) or datetime.utcnow()
    snapshot = {
        "user_id": user_id,
        "exchange": exchange_name,
        "settlement_asset": raw.get("currency") or raw.get("asset") or "USDT",
        "equity": _safe_float(raw.get("equity")),
        "available_balance": _safe_float(raw.get("availableBalance")),
        "frozen_balance": _safe_float(raw.get("frozenBalance")),
        "cash_balance": _safe_float(raw.get("cashBalance")),
        "position_margin": _safe_float(raw.get("positionMargin")),
        "unrealized_pnl": _safe_float(raw.get("unrealized")),
        "bonus": _safe_float(raw.get("bonus")),
        "available_cash": _safe_float(raw.get("availableCash")),
        "debt_amount": _safe_float(raw.get("debtAmount")),
        "source_ts": source_ts,
    }
    return snapshot, _coverage("futures_account_assets", rows=[snapshot], status="fresh", complete=True, source_total=1, page_num=1, page_size=1, exhausted=True)


# ── Phase 2B capital-flow history helpers ────────────────────────────────────


def _fetch_funding_history_with_coverage(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from backend.services.phase2b_ledger import coerce_funding_row

    if not (exchange_name == "mexc" and hasattr(exchange, "contract_private_get_position_funding_records")):
        return [], _coverage(
            "funding", rows=[], status="unavailable", complete=False, reason="stream_not_supported"
        )
    rows, paging = _paginate_mexc_history(
        exchange.contract_private_get_position_funding_records, "funding"
    )
    normalised = [coerce_funding_row(r) for r in rows]
    return normalised, _coverage("funding", rows=normalised, **paging)


def _fetch_futures_transfers_with_coverage(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from backend.services.phase2b_ledger import coerce_futures_transfer_row

    if not (exchange_name == "mexc" and hasattr(exchange, "contract_private_get_account_transfer_record")):
        return [], _coverage(
            "futures_transfers",
            rows=[],
            status="unavailable",
            complete=False,
            reason="stream_not_supported",
        )
    rows, paging = _paginate_mexc_history(
        exchange.contract_private_get_account_transfer_record, "futures_transfers"
    )
    normalised = [coerce_futures_transfer_row(r) for r in rows]
    return normalised, _coverage("futures_transfers", rows=normalised, **paging)


def _fetch_deposits_with_coverage(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from backend.services.phase2b_ledger import coerce_deposit_row

    method = getattr(exchange, "fetch_deposits", None) or getattr(exchange, "fetchDeposits", None)
    if not callable(method):
        return [], _coverage(
            "deposits", rows=[], status="unavailable", complete=False, reason="stream_not_supported"
        )
    try:
        raw = method(limit=100) or []
    except Exception as exc:
        return [], _coverage(
            "deposits",
            rows=[],
            status="error",
            complete=False,
            error_code=str(getattr(exc, "code", "exchange_error")),
            error_message=_redact_error(str(exc)),
        )
    normalised = [coerce_deposit_row(r if isinstance(r, dict) else {"amount": r}) for r in raw]
    complete = len(normalised) < 100
    return normalised, _coverage(
        "deposits",
        rows=normalised,
        status="fresh" if complete else "partial",
        complete=complete,
        reason=None if complete else "exchange_boundary_before_source_total",
        source_total=len(normalised) if complete else None,
        page_num=1,
        page_size=100,
        exhausted=complete,
        unrecoverable_gaps=[] if complete else [
            {"stream": "deposits", "reason": "exchange_boundary_before_source_total"}
        ],
    )


def _fetch_withdrawals_with_coverage(
    exchange: Any,
    user_id: int,
    exchange_name: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from backend.services.phase2b_ledger import coerce_withdrawal_row

    method = getattr(exchange, "fetch_withdrawals", None) or getattr(exchange, "fetchWithdrawals", None)
    if not callable(method):
        return [], _coverage(
            "withdrawals",
            rows=[],
            status="unavailable",
            complete=False,
            reason="stream_not_supported",
        )
    try:
        raw = method(limit=100) or []
    except Exception as exc:
        return [], _coverage(
            "withdrawals",
            rows=[],
            status="error",
            complete=False,
            error_code=str(getattr(exc, "code", "exchange_error")),
            error_message=_redact_error(str(exc)),
        )
    normalised = [coerce_withdrawal_row(r if isinstance(r, dict) else {"amount": r}) for r in raw]
    complete = len(normalised) < 100
    return normalised, _coverage(
        "withdrawals",
        rows=normalised,
        status="fresh" if complete else "partial",
        complete=complete,
        reason=None if complete else "exchange_boundary_before_source_total",
        source_total=len(normalised) if complete else None,
        page_num=1,
        page_size=100,
        exhausted=complete,
        unrecoverable_gaps=[] if complete else [
            {"stream": "withdrawals", "reason": "exchange_boundary_before_source_total"}
        ],
    )


def _paginate_mexc_history(method: Any, stream: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows_all: List[Dict[str, Any]] = []
    source_total: Optional[int] = None
    page = 1
    page_size = 100
    exhausted = False
    while True:
        resp: Dict[str, Any] = {}
        err: Optional[Tuple[str, str]] = None
        for attempt in range(4):
            try:
                resp = method({"pageSize": page_size, "pageNum": page}) or {}
                err = _mexc_error(resp)
                if err is None:
                    break
            except Exception as exc:  # pragma: no cover - defensive ccxt path
                err = (str(getattr(exc, "code", "exchange_error")), str(exc))
            if attempt < 3 and err and err[0] in {"429", "510", "rate_limit_error"}:
                time.sleep(min(2 ** attempt, 4.0))
                continue
            status = "partial" if rows_all else "error"
            return rows_all, {
                "status": status,
                "complete": False,
                "reason": "mexc_rate_limit" if err and err[0] in {"429", "510", "rate_limit_error"} else "mexc_error",
                "error_code": err[0] if err else "exchange_error",
                "error_message": _redact_error(err[1] if err else "exchange error"),
                "source_total": source_total,
                "page_num": page,
                "page_size": page_size,
                "exhausted": False,
                "unrecoverable_gaps": [{"stream": stream, "reason": "exchange_boundary_or_rate_limit", "page_num": page}],
            }
        page_data = resp.get("data")
        if isinstance(page_data, list):
            rows = page_data
            total_pages = page
            source_total = len(rows_all) + len(rows)
        elif isinstance(page_data, dict):
            # MEXC history endpoints disagree on collection keys:
            # positions/orders often use "list"; funding/transfers use "resultList"
            # (see ccxt mexc.fetch_funding_history sample payload).
            rows = (
                page_data.get("list")
                or page_data.get("result")
                or page_data.get("resultList")
                or page_data.get("dataList")
                or page_data.get("rows")
                or page_data.get("records")
                or []
            )
            total_pages = int(
                page_data.get("totalPage")
                or page_data.get("pages")
                or page_data.get("totalPages")
                or page
            )
            source_total = int(
                page_data.get("total")
                or page_data.get("totalCount")
                or source_total
                or 0
            ) or None
        else:
            rows = []
            total_pages = page
        rows_all.extend(rows)
        # Empty page with more totalPages remaining: stop only when we have
        # actually exhausted declared pages, not merely because this page is empty.
        if page >= total_pages:
            exhausted = True
            break
        if not rows:
            # No rows but exchange claims more pages — still stop to avoid
            # infinite empty loops; mark incomplete below if source_total > fetched.
            exhausted = False
            break
        page += 1
    complete = bool(exhausted and (source_total is None or len(rows_all) >= source_total))
    # Empty history that the exchange reports as total=0 / exhausted is complete.
    if complete is False and not rows_all and source_total in (None, 0) and exhausted:
        complete = True
    return rows_all, {
        "status": "fresh" if complete else "partial",
        "complete": complete,
        "reason": None if complete else "exchange_boundary_before_source_total",
        "source_total": source_total if source_total is not None else len(rows_all),
        "page_num": page,
        "page_size": page_size,
        "exhausted": exhausted,
        "unrecoverable_gaps": [] if complete else [{"stream": stream, "reason": "exchange_boundary_before_source_total"}],
    }


def _normalise_mexc_position_rows(exchange: Any, rows: List[Dict[str, Any]], user_id: int, exchange_name: str) -> List[Dict[str, Any]]:
    markets = getattr(exchange, "markets", {}) or {}
    result: List[Dict[str, Any]] = []
    for raw in rows:
        symbol = str(raw.get("symbol", "")).replace("_", "")
        market = markets.get(symbol) or markets.get(symbol[:-4] + "/" + symbol[-4:]) if symbol else None
        contract_size = _safe_float((market or {}).get("contractSize")) or 1.0
        open_time = _mexc_datetime(raw.get("createTime"))
        close_time = _mexc_datetime(raw.get("updateTime"))
        profit_ratio = _safe_float(raw.get("profitRatio"))
        pnl = _safe_float(raw.get("closeProfitLoss")) or 0.0
        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "exchange_position_id": str(raw.get("positionId")) if raw.get("positionId") is not None else None,
            "symbol": symbol,
            "side": "long" if str(raw.get("positionType", "1")) == "1" else "short",
            "size": _safe_float(raw.get("closeVol")) or 0.0,
            "entry_price": _safe_float(raw.get("holdAvgPrice")) or 0.0,
            "exit_price": _safe_float(raw.get("closeAvgPrice")) or 0.0,
            "pnl": pnl,
            "pnl_percent": (profit_ratio or 0.0) * 100,
            "reported_pnl": pnl,
            "reported_roi_pct": (profit_ratio or 0.0) * 100,
            "leverage": _safe_float(raw.get("leverage")) or 1.0,
            "open_time": open_time,
            "close_time": close_time,
            "close_reason": "closed",
            "contract_size": contract_size,
            "source_state": str(raw.get("state")) if raw.get("state") is not None else None,
            "source_updated_at": close_time,
        })
    result.sort(key=lambda p: (p["close_time"] or p["open_time"] or datetime.utcnow()), reverse=True)
    return result


def _normalise_mexc_order_rows(rows: List[Dict[str, Any]], user_id: int, exchange_name: str) -> List[Dict[str, Any]]:
    side_map = {"1": ("buy", "Open Long"), "2": ("sell", "Close Long"), "3": ("sell", "Open Short"), "4": ("buy", "Close Short")}
    type_map = {"1": "limit", "2": "market", "5": "post_only"}
    state_map = {"3": "filled", "4": "cancelled", "5": "partially_filled"}
    result: List[Dict[str, Any]] = []
    for raw in rows:
        side, side_action = side_map.get(str(raw.get("side", "")), ("", str(raw.get("side", ""))))
        timestamp = _mexc_datetime(raw.get("createTime")) or datetime.utcnow()
        filled = _safe_float(raw.get("dealVol")) or 0.0
        filled_price = _safe_float(raw.get("dealAvgPrice")) or 0.0
        result.append({
            "user_id": user_id,
            "exchange": exchange_name,
            "exchange_order_id": str(raw.get("orderId")) if raw.get("orderId") is not None else None,
            "symbol": str(raw.get("symbol", "")).replace("_", ""),
            "type": type_map.get(str(raw.get("orderType", "")), str(raw.get("orderType", "")) or "limit"),
            "side": side,
            "side_action": side_action,
            "price": _safe_float(raw.get("price")) or 0.0,
            "amount": _safe_float(raw.get("vol")) or 0.0,
            "filled": filled,
            "filled_price": filled_price,
            "cost": filled * filled_price,
            "status": state_map.get(str(raw.get("state", "")), str(raw.get("state", ""))),
            "timestamp": timestamp,
            "fee": _safe_float(raw.get("fee")) or 0.0,
            "fee_currency": raw.get("feeCurrency") or "USDT",
            "leverage": _safe_float(raw.get("leverage")) or 1.0,
            "reduce_only": 1 if str(raw.get("openType", "")) == "2" else 0,
            "source_updated_at": _mexc_datetime(raw.get("updateTime")) or timestamp,
        })
    result.sort(key=lambda o: o["timestamp"], reverse=True)
    return result


def _coverage(stream: str, rows: List[Dict[str, Any]], status: str = "fresh", complete: bool = True, reason: Optional[str] = None, source_total: Optional[int] = None, page_num: int = 1, page_size: int = 100, exhausted: bool = True, error_code: Optional[str] = None, error_message: Optional[str] = None, unrecoverable_gaps: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    times = [
        row.get("close_time") or row.get("timestamp") or row.get("source_ts") or row.get("occurred_at")
        for row in rows
    ]
    times = [ts for ts in times if ts is not None]
    return {
        "stream": stream,
        "status": status,
        "complete": complete,
        "reason": reason,
        "oldest_source_ts": min(times) if times else None,
        "newest_source_ts": max(times) if times else None,
        "rows_fetched_total": len(rows),
        "source_total": source_total if source_total is not None else len(rows),
        "cursor": {"page_num": page_num, "page_size": page_size, "exhausted": exhausted},
        "last_success_at": datetime.utcnow() if complete else None,
        "last_attempt_at": datetime.utcnow(),
        "error_code": error_code,
        "error_message": error_message,
        "unrecoverable_gaps": unrecoverable_gaps or [],
    }


def _mexc_error(resp: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    code = resp.get("code") or resp.get("status")
    if resp.get("success") is False or str(code) in {"429", "510"}:
        return str(code or "exchange_error"), str(resp.get("message") or resp.get("msg") or "MEXC request failed")
    return None


def _redact_error(message: str) -> str:
    redacted = str(message).replace("synthetic-key", "[redacted]")
    for token in ("apiKey", "secret", "Authorization"):
        redacted = redacted.replace(token, "[redacted]")
    return redacted


def _mexc_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.utcfromtimestamp(int(value) / 1000.0)
    except (TypeError, ValueError):
        return None


# ── Low-level helpers ────────────────────────────────────────────────────────


def _safe_float(value: Any) -> Optional[float]:
    """Convert *value* to float, or return ``None`` if it's None/missing."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
