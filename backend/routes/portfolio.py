"""Portfolio routes — connect / disconnect / refresh / get cached data for a
single exchange.

Endpoints
---------
POST   /api/v1/portfolio/{exchange}/connect      — store encrypted API keys, validate via fetchBalance
DELETE /api/v1/portfolio/{exchange}/disconnect   — remove keys + clear cached portfolio data
GET    /api/v1/portfolio/{exchange}/keys        — return {connected: bool, masked_key: str}
POST   /api/v1/portfolio/{exchange}/refresh      — fetch live data, cache to DB tables, return results
GET    /api/v1/portfolio/{exchange}               — return cached data + last_refreshed

All endpoints require JWT auth (``Depends(get_current_user)``).

Error mapping
-------------
* 401 — not authenticated (raised by ``get_current_user``)
* 404 — exchange not in the supported-exchanges list
* 400 — invalid credentials on connect, missing keys on refresh
* 429 — exchange rate-limited a fetch
* 502 — exchange timeout, network error, or other upstream failure
* 501 — ccxt is not importable (connect endpoint only)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import (
    ExchangeKey,
    PortfolioBalance,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioTrade,
    User,
)
from backend.services import exchange_service
from backend.services.exchange_service import (
    SUPPORTED_EXCHANGES,
    ExchangeAuthError,
    ExchangeError,
    ExchangeRateLimitError,
    ExchangeTimeoutError,
    create_exchange_instance,
    fetch_portfolio,
    get_exchange,
    get_supported_exchanges,
    is_ccxt_available,
    validate_exchange_keys,
)
from backend.services.encryption import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


class ExchangesResponse(BaseModel):
    """Response for `GET /api/v1/portfolio/exchanges`."""

    exchanges: List[str]


# ── Pydantic request/response schemas ────────────────────────────────────────


class ConnectRequest(BaseModel):
    """Body for POST /connect — plaintext API credentials (HTTPS only)."""

    api_key: str = Field(..., min_length=1, description="Exchange API key")
    api_secret: str = Field(..., min_length=1, description="Exchange API secret")


class ConnectResponse(BaseModel):
    """Returned after a successful connect."""

    connected: bool = True
    exchange: str
    masked_key: str


class KeysResponse(BaseModel):
    """Response for GET /keys."""

    connected: bool
    masked_key: Optional[str] = None


class BalanceItem(BaseModel):
    asset: str
    free: float
    locked: float
    total: float
    usd_value: Optional[float] = None


class PositionItem(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    pnl: float
    pnl_percent: float
    leverage: float
    liquidation_price: Optional[float] = None
    margin: float
    contract_size: Optional[float] = None


class TradeItem(BaseModel):
    symbol: str
    side: str
    type: str
    price: float
    amount: float
    cost: float
    fee: Optional[float] = None
    fee_currency: Optional[str] = None
    timestamp: datetime
    exchange_trade_id: str


class SnapshotItem(BaseModel):
    total_balance_usd: Optional[float] = None
    total_pnl_usd: float
    open_positions: int
    timestamp: datetime


class PortfolioResponse(BaseModel):
    """Shape of refresh/get responses."""

    exchange: str
    balances: List[BalanceItem]
    positions: List[PositionItem]
    trades: List[TradeItem]
    snapshot: Optional[SnapshotItem] = None
    last_refreshed: Optional[str] = None
    stale: bool = True


class PortfolioErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────────────────────


def _require_supported_exchange(exchange: str) -> str:
    """Return the normalised exchange slug or raise HTTP 404 / 501.

    * Loads the ``SUPPORTED_EXCHANGES`` dict (lazy ccxt import).
    * Returns 501 Not Implemented if ccxt is not importable.
    * Returns 404 Not Found if *exchange* is not in the supported list.
    """
    exchange_slug = exchange.strip().lower()
    if not is_ccxt_available():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="ccxt package is not installed — portfolio integration is disabled",
            headers={"X-Error-Code": "ccxt_not_installed"},
        )
    exchange_service._load_supported_exchanges()
    if exchange_slug not in SUPPORTED_EXCHANGES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Exchange '{exchange_slug}' is not supported. "
                f"Supported: {sorted(SUPPORTED_EXCHANGES)}"
            ),
            headers={"X-Error-Code": "unsupported_exchange"},
        )
    return exchange_slug


def _mask_api_key(api_key: str) -> str:
    """Return a masked version of *api_key* (e.g. ``mex••••c3k``).

    Shows the first 3 and last 3 characters; hides the middle with dots.
    """
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "•" * len(api_key)
    return f"{api_key[:3]}{'•' * 5}{api_key[-3:]}"


def _map_exchange_error(exc: ExchangeError, action: str) -> HTTPException:
    """Map an :class:`ExchangeError` to an ``HTTPException``.

    *action* is used in the detail message (e.g. ``"connect"``, ``"refresh"``).
    """
    if isinstance(exc, ExchangeRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.args[0] if exc.args else "Rate limited by exchange",
            headers={"X-Error-Code": exc.code, "Retry-After": "30"},
        )
    if isinstance(exc, ExchangeAuthError):
        # Invalid credentials during refresh → 502; invalid on connect → 400
        # (caller decides).  We default to 502 here; connect handler overrides.
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Exchange authentication failed during {action}: {exc}. "
                "Your API key may be invalid or revoked — please reconnect."
            ),
            headers={"X-Error-Code": exc.code},
        )
    if isinstance(exc, ExchangeTimeoutError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Exchange request timed out during {action}: {exc}",
            headers={"X-Error-Code": exc.code},
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Exchange error during {action}: {exc}",
        headers={"X-Error-Code": exc.code},
    )


def _serialise_balance(row: PortfolioBalance) -> Dict[str, Any]:
    return {
        "asset": row.asset,
        "free": row.free,
        "locked": row.locked,
        "total": row.total,
        "usd_value": row.usd_value,
    }


def _serialise_position(row: PortfolioPosition) -> Dict[str, Any]:
    return {
        "symbol": row.symbol,
        "side": row.side,
        "size": row.size,
        "entry_price": row.entry_price,
        "mark_price": row.mark_price,
        "pnl": row.pnl,
        "pnl_percent": row.pnl_percent,
        "leverage": row.leverage,
        "liquidation_price": row.liquidation_price,
        "margin": row.margin,
        "contract_size": row.contract_size,
    }


def _serialise_trade(row: PortfolioTrade) -> Dict[str, Any]:
    return {
        "symbol": row.symbol,
        "side": row.side,
        "type": row.type,
        "price": row.price,
        "amount": row.amount,
        "cost": row.cost,
        "fee": row.fee,
        "fee_currency": row.fee_currency,
        "timestamp": row.timestamp,
        "exchange_trade_id": row.exchange_trade_id,
    }


def _serialise_snapshot(row: PortfolioSnapshot) -> Dict[str, Any]:
    return {
        "total_balance_usd": row.total_balance_usd,
        "total_pnl_usd": row.total_pnl_usd,
        "open_positions": row.open_positions,
        "timestamp": row.timestamp,
    }


def _get_iso_ts(snapshot: Optional[PortfolioSnapshot]) -> Optional[str]:
    """Return ``snapshot.timestamp`` as ISO 8601 string, or ``None``."""
    if snapshot is None:
        return None
    ts = snapshot.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "/exchanges",
    response_model=ExchangesResponse,
    summary="List supported exchanges",
)
async def list_supported_exchanges(
    current_user: User = Depends(get_current_user),
) -> ExchangesResponse:
    """Return the list of exchange slugs supported by the backend.

    The list is sourced from ``SUPPORTED_EXCHANGES`` (which reflects what
    ccxt can import). Useful for driving the frontend exchange selector
    dropdown.
    """
    # If ccxt isn't installed we still return an empty list (rather than 501)
    # so the frontend can degrade gracefully.
    exchanges = sorted(get_supported_exchanges().keys()) if is_ccxt_available() else []
    return ExchangesResponse(exchanges=exchanges)


@router.post(
    "/{exchange}/connect",
    response_model=ConnectResponse,
    responses={
        400: {"model": PortfolioErrorResponse, "description": "Invalid credentials"},
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
        502: {"model": PortfolioErrorResponse, "description": "Exchange error"},
    },
)
async def connect_exchange(
    exchange: str,
    body: ConnectRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConnectResponse:
    """Validate and store exchange API credentials for the current user.

    The keys are validated by calling ``fetchBalance()`` before being stored.
    Invalid credentials return HTTP 400; exchange errors return 502.
    """
    exchange_slug = _require_supported_exchange(exchange)

    # 1. Validate via fetchBalance
    try:
        exchange_instance = create_exchange_instance(
            exchange_slug, body.api_key, body.api_secret
        )
        validate_exchange_keys(exchange_instance)
    except ExchangeAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid API credentials: {exc}. Verify key, secret, and permissions.",
            headers={"X-Error-Code": exc.code},
        ) from exc
    except ExchangeRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"X-Error-Code": exc.code, "Retry-After": "30"},
        ) from exc
    except ExchangeError as exc:
        raise _map_exchange_error(exc, action="connect") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
            headers={"X-Error-Code": "unsupported_exchange"},
        ) from exc

    # 2. Encrypt and upsert keys (unique constraint on user_id + exchange)
    api_key_encrypted = encrypt_api_key(body.api_key)
    api_secret_encrypted = encrypt_api_key(body.api_secret)

    result = await session.execute(
        select(ExchangeKey).where(
            ExchangeKey.user_id == current_user.id,
            ExchangeKey.exchange == exchange_slug,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.api_key_encrypted = api_key_encrypted
        existing.api_secret_encrypted = api_secret_encrypted
        existing.updated_at = datetime.utcnow()
    else:
        session.add(ExchangeKey(
            user_id=current_user.id,
            exchange=exchange_slug,
            api_key_encrypted=api_key_encrypted,
            api_secret_encrypted=api_secret_encrypted,
        ))
    await session.commit()

    return ConnectResponse(
        connected=True,
        exchange=exchange_slug,
        masked_key=_mask_api_key(body.api_key),
    )


@router.delete(
    "/{exchange}/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
    },
)
async def disconnect_exchange(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove stored API keys and clear all cached portfolio data for the
    given exchange (balances, positions, trades, snapshots).
    """
    exchange_slug = _require_supported_exchange(exchange)

    # Delete API keys
    await session.execute(
        delete(ExchangeKey).where(
            ExchangeKey.user_id == current_user.id,
            ExchangeKey.exchange == exchange_slug,
        )
    )

    # Delete cached portfolio data — TTL refresh on next connect/refresh.
    await session.execute(
        delete(PortfolioBalance).where(
            PortfolioBalance.user_id == current_user.id,
            PortfolioBalance.exchange == exchange_slug,
        )
    )
    await session.execute(
        delete(PortfolioPosition).where(
            PortfolioPosition.user_id == current_user.id,
            PortfolioPosition.exchange == exchange_slug,
        )
    )
    await session.execute(
        delete(PortfolioTrade).where(
            PortfolioTrade.user_id == current_user.id,
            PortfolioTrade.exchange == exchange_slug,
        )
    )
    await session.execute(
        delete(PortfolioSnapshot).where(
            PortfolioSnapshot.user_id == current_user.id,
            PortfolioSnapshot.exchange == exchange_slug,
        )
    )
    await session.commit()


@router.get(
    "/{exchange}/keys",
    response_model=KeysResponse,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_exchange_keys(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> KeysResponse:
    """Return whether API keys are stored for the current user + exchange.

    Returns ``{connected: bool, masked_key: str}`` — no secret material is
    surfaced, only a masked preview of the API key.
    """
    exchange_slug = _require_supported_exchange(exchange)

    result = await session.execute(
        select(ExchangeKey).where(
            ExchangeKey.user_id == current_user.id,
            ExchangeKey.exchange == exchange_slug,
        )
    )
    key_row = result.scalar_one_or_none()
    if key_row is None:
        return KeysResponse(connected=False, masked_key=None)

    try:
        api_key_plain = decrypt_api_key(key_row.api_key_encrypted)
        masked = _mask_api_key(api_key_plain)
    except Exception as exc:
        logger.warning(
            "Failed to decrypt API key for user %d / %s: %s",
            current_user.id, exchange_slug, exc,
        )
        # Key exists but can't be decrypted — likely env key rotation.
        # Treat as connected but show no masked key.
        masked = None

    return KeysResponse(connected=True, masked_key=masked)


@router.post(
    "/{exchange}/refresh",
    response_model=PortfolioResponse,
    responses={
        400: {"model": PortfolioErrorResponse, "description": "No stored keys"},
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        429: {"model": PortfolioErrorResponse, "description": "Rate limited"},
        502: {"model": PortfolioErrorResponse, "description": "Exchange error"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def refresh_portfolio(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PortfolioResponse:
    """Fetch live portfolio data from the exchange, cache it to DB tables, and
    return the result.

    Caches balances, positions, and trades (upsert-safe) and records a
    snapshot row with the latest totals.
    """
    exchange_slug = _require_supported_exchange(exchange)

    # 1. Get exchange instance — raises ValueError if no keys stored
    try:
        exchange_instance = await get_exchange(
            user_id=current_user.id,
            exchange_name=exchange_slug,
            db_session=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
            headers={"X-Error-Code": "no_api_keys"},
        ) from exc

    # 2. Fetch live portfolio data
    try:
        data = await fetch_portfolio(
            exchange_instance=exchange_instance,
            user_id=current_user.id,
        )
    except ExchangeRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"X-Error-Code": exc.code, "Retry-After": "30"},
        ) from exc
    except ExchangeAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Exchange rejected the API key: {exc}. "
                "Your key may be invalid or revoked — please reconnect."
            ),
            headers={"X-Error-Code": exc.code},
        ) from exc
    except ExchangeTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Exchange request timed out: {exc}",
            headers={"X-Error-Code": exc.code},
        ) from exc
    except ExchangeError as exc:
        raise _map_exchange_error(exc, action="refresh") from exc

    # 3. Persist to cache tables
    now = datetime.utcnow()
    await _persist_portfolio_data(session, current_user.id, exchange_slug, data, now)
    await session.commit()

    # 4. Build response (includes the freshly-fetched snapshot)
    snapshot = await _get_latest_snapshot(session, current_user.id, exchange_slug)
    return PortfolioResponse(
        exchange=exchange_slug,
        balances=[BalanceItem(**b) for b in data["balances"]],
        positions=[PositionItem(**p) for p in data["positions"]],
        trades=[TradeItem(**t) for t in data["trades"]],
        snapshot=SnapshotItem(**_serialise_snapshot(snapshot)) if snapshot else None,
        last_refreshed=_get_iso_ts(snapshot),
        stale=False,
    )


@router.get(
    "/{exchange}",
    response_model=PortfolioResponse,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_portfolio(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PortfolioResponse:
    """Return cached portfolio data for the current user + exchange.

    Makes **no** outbound API call — reads directly from cache tables. Use
    ``POST /refresh`` to refresh the cache.
    """
    exchange_slug = _require_supported_exchange(exchange)

    balances = await _load_balances(session, current_user.id, exchange_slug)
    positions = await _load_positions(session, current_user.id, exchange_slug)
    trades = await _load_trades(session, current_user.id, exchange_slug)
    snapshot = await _get_latest_snapshot(session, current_user.id, exchange_slug)

    return PortfolioResponse(
        exchange=exchange_slug,
        balances=[BalanceItem(**_serialise_balance(b)) for b in balances],
        positions=[PositionItem(**_serialise_position(p)) for p in positions],
        trades=[TradeItem(**_serialise_trade(t)) for t in trades],
        snapshot=SnapshotItem(**_serialise_snapshot(snapshot)) if snapshot else None,
        last_refreshed=_get_iso_ts(snapshot),
        stale=True,
    )


# ── DB persistence helpers ───────────────────────────────────────────────────


async def _persist_portfolio_data(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    data: Dict[str, List[Dict[str, Any]]],
    now: datetime,
) -> None:
    """Upsert balances / positions / trades and insert a snapshot row.

    Balances and positions are fully replaced (delete-then-insert) since they
    represent the current state; trades are upserted (unique on
    ``exchange_trade_id``) to avoid duplication.
    """
    # ── Replace balances ────────────────────────────────────────────
    await session.execute(
        delete(PortfolioBalance).where(
            PortfolioBalance.user_id == user_id,
            PortfolioBalance.exchange == exchange,
        )
    )
    for bal in data["balances"]:
        session.add(PortfolioBalance(
            user_id=user_id,
            exchange=exchange,
            asset=bal["asset"],
            free=bal["free"],
            locked=bal["locked"],
            total=bal["total"],
            usd_value=bal.get("usd_value"),
            updated_at=now,
        ))

    # ── Replace positions ───────────────────────────────────────────
    await session.execute(
        delete(PortfolioPosition).where(
            PortfolioPosition.user_id == user_id,
            PortfolioPosition.exchange == exchange,
        )
    )
    for pos in data["positions"]:
        session.add(PortfolioPosition(
            user_id=user_id,
            exchange=exchange,
            symbol=pos["symbol"],
            side=pos["side"],
            size=pos["size"],
            entry_price=pos["entry_price"],
            mark_price=pos["mark_price"],
            pnl=pos["pnl"],
            pnl_percent=pos["pnl_percent"],
            leverage=pos["leverage"],
            liquidation_price=pos["liquidation_price"],
            margin=pos["margin"],
            contract_size=pos.get("contract_size", 1.0),
            updated_at=now,
        ))

    # ── Upsert trades (skip duplicates) ────────────────────────────
    # SQLite: the unique constraint on (exchange, exchange_trade_id, user_id)
    # will reject duplicates. Use "INSERT OR IGNORE" semantics via a
    # per-trade existence check — simpler and portable across DBs.
    trade_ids: List[str] = [
        t["exchange_trade_id"] for t in data["trades"] if t["exchange_trade_id"]
    ]
    existing_trade_ids: set[str] = set()
    if trade_ids:
        result = await session.execute(
            select(PortfolioTrade.exchange_trade_id).where(
                PortfolioTrade.user_id == user_id,
                PortfolioTrade.exchange == exchange,
                PortfolioTrade.exchange_trade_id.in_(trade_ids),
            )
        )
        existing_trade_ids = set(result.scalars().all())

    for trade in data["trades"]:
        if trade["exchange_trade_id"] in existing_trade_ids:
            continue
        session.add(PortfolioTrade(
            user_id=user_id,
            exchange=exchange,
            symbol=trade["symbol"],
            side=trade["side"],
            type=trade["type"],
            price=trade["price"],
            amount=trade["amount"],
            cost=trade["cost"],
            fee=trade["fee"],
            fee_currency=trade["fee_currency"],
            timestamp=trade["timestamp"],
            exchange_trade_id=trade["exchange_trade_id"],
        ))

    # ── Snapshot row ────────────────────────────────────────────────
    total_pnl = sum(p["pnl"] for p in data["positions"])
    open_positions = len(data["positions"])
    session.add(PortfolioSnapshot(
        user_id=user_id,
        exchange=exchange,
        # total_balance_usd is computed downstream (frontend uses ticker prices
        # for USDT-quoted assets). Stored as None until a valuation step is added.
        total_balance_usd=None,
        total_pnl_usd=total_pnl,
        open_positions=open_positions,
        timestamp=now,
    ))


async def _load_balances(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[PortfolioBalance]:
    result = await session.execute(
        select(PortfolioBalance).where(
            PortfolioBalance.user_id == user_id,
            PortfolioBalance.exchange == exchange,
        )
    )
    return list(result.scalars().all())


async def _load_positions(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[PortfolioPosition]:
    result = await session.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.user_id == user_id,
            PortfolioPosition.exchange == exchange,
        )
    )
    return list(result.scalars().all())


async def _load_trades(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[PortfolioTrade]:
    result = await session.execute(
        select(PortfolioTrade)
        .where(
            PortfolioTrade.user_id == user_id,
            PortfolioTrade.exchange == exchange,
        )
        .order_by(PortfolioTrade.timestamp.desc())
        .limit(50)
    )
    return list(result.scalars().all())


async def _get_latest_snapshot(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Optional[PortfolioSnapshot]:
    result = await session.execute(
        select(PortfolioSnapshot)
        .where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.exchange == exchange,
        )
        .order_by(PortfolioSnapshot.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
