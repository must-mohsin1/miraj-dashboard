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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import (
    Analysis,
    CapitalFlowLedger,
    ExchangeKey,
    ExchangeSyncState,
    FuturesAccountSnapshot,
    OrderHistory,
    PortfolioBalance,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioTrade,
    PositionHistory,
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
    fetch_history,
    fetch_portfolio,
    get_exchange,
    get_supported_exchanges,
    is_ccxt_available,
    validate_exchange_keys,
)
from backend.services.encryption import decrypt_api_key, encrypt_api_key
from backend.services.phase2a_sync import (
    latest_futures_account_snapshot,
    persist_phase2a_sync_payload,
)
from backend.services.phase2b_ledger import persist_capital_flow_payload

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


class PositionHistoryItem(BaseModel):
    exchange_position_id: Optional[str] = None
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_percent: float
    leverage: float
    open_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    close_reason: Optional[str] = None
    contract_size: Optional[float] = None


class OrderHistoryItem(BaseModel):
    exchange_order_id: Optional[str] = None
    symbol: str
    type: str
    side: str
    side_action: Optional[str] = None
    price: float
    amount: float
    filled: float
    filled_price: Optional[float] = None
    cost: float
    status: str
    timestamp: datetime
    fee: Optional[float] = None
    fee_currency: Optional[str] = None
    leverage: Optional[float] = None
    reduce_only: Optional[int] = None


class SnapshotItem(BaseModel):
    total_balance_usd: Optional[float] = None
    total_pnl_usd: float
    open_positions: int
    timestamp: datetime


class FuturesAccountItem(BaseModel):
    settlement_asset: str
    equity: Optional[float] = None
    available_balance: Optional[float] = None
    frozen_balance: Optional[float] = None
    cash_balance: Optional[float] = None
    position_margin: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    bonus: Optional[float] = None
    available_cash: Optional[float] = None
    debt_amount: Optional[float] = None
    source_ts: datetime
    synced_at: datetime


class SyncCoverageItem(BaseModel):
    stream: str
    status: str
    complete: bool
    reason: Optional[str] = None
    oldest_source_ts: Optional[datetime] = None
    newest_source_ts: Optional[datetime] = None
    rows_fetched_total: int = 0
    source_total: Optional[int] = None
    cursor: Optional[Dict[str, Any]] = None
    last_success_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    unrecoverable_gaps: List[Dict[str, Any]] = []
    supported_by_exchange: Optional[bool] = None


class SyncStatusResponse(BaseModel):
    exchange: str
    sync: List[SyncCoverageItem]
    futures_account: Optional[FuturesAccountItem] = None
    partial: bool = True


class PortfolioResponse(BaseModel):
    """Shape of refresh/get responses."""

    exchange: str
    balances: List[BalanceItem]
    positions: List[PositionItem]
    trades: List[TradeItem]
    position_history: List[PositionHistoryItem] = []
    order_history: List[OrderHistoryItem] = []
    snapshot: Optional[SnapshotItem] = None
    sync: List[SyncCoverageItem] = []
    futures_account: Optional[FuturesAccountItem] = None
    partial: bool = False
    last_refreshed: Optional[str] = None
    stale: bool = True


class CapitalFlowEntryItem(BaseModel):
    """Single capital-flow ledger row for GET .../capital-flow."""

    id: int
    entry_type: str
    exchange_entry_id: Optional[str] = None
    asset: str
    amount: Optional[float] = None
    signed_amount: Optional[float] = None
    status: Optional[str] = None
    occurred_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    synced_at: datetime


class CapitalFlowResponse(BaseModel):
    """Paginated capital-flow ledger + focused four-stream coverage."""

    exchange: str
    entries: List[CapitalFlowEntryItem]
    sync: List[SyncCoverageItem]
    partial: bool = False
    limit: int = 200
    offset: int = 0


# ── Position alert schemas (cross-reference with Miraj scan) ────────────────


class PositionAlert(BaseModel):
    """A single alert on a position (e.g. QQE flip, structure conflict)."""

    type: str = Field(description="QQE_FLIP / STRUCTURE / CONFLUENCE / LIQ_DISTANCE")
    severity: str = Field(description="WARNING or DANGER")
    message: str
    action: Optional[str] = None


class PositionAlertItem(BaseModel):
    """Aggregated alerts for a single open position."""

    symbol: str
    position_side: str
    position_size: float
    max_severity: Optional[str] = None
    alerts: List[PositionAlert]


class PositionAlertsResponse(BaseModel):
    """Response for GET /api/v1/portfolio/{exchange}/position-alerts."""

    exchange: str
    total_alerts: int
    danger_count: int
    warning_count: int
    positions: List[PositionAlertItem]


class HistoryResponse(BaseModel):
    """Response for `GET /api/v1/portfolio/{exchange}/history`."""

    exchange: str
    position_history: List[PositionHistoryItem]
    order_history: List[OrderHistoryItem]
    sync: List[SyncCoverageItem] = []
    futures_account: Optional[FuturesAccountItem] = None
    partial: bool = False


# ── Trade attribution (scan linking) ─────────────────────────────────────────


class TradeAttributionItem(BaseModel):
    """A single closed position linked to the scan that preceded its entry.

    The ``scan_*`` fields are ``None`` when no recorded scan exists for that
    symbol, or when no scan ran before the position's ``open_time``.
    """

    position_symbol: str
    position_side: str
    entry_price: float
    exit_price: float
    pnl: float
    pnl_percent: float = 0.0
    leverage: float = 1.0
    open_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    close_reason: Optional[str] = None
    # ── Linked scan (nearest scan at/before open_time) ──
    scan_score: Optional[float] = Field(
        None, description="Confluence score (0–30) of the pre-entry scan"
    )
    scan_direction: Optional[str] = Field(
        None, description="LONG / SHORT inferred from the scan's trade plan"
    )
    scan_qqe_signals: Optional[Dict[str, Any]] = Field(
        None,
        description="Per-TF QQE summary {daily,4h,1h → {trend,strength}} at entry",
    )


class TradeAttributionResponse(BaseModel):
    """Response for `GET /api/v1/portfolio/{exchange}/trade-attribution`."""

    exchange: str
    total_trades: int
    high_confidence_trades: int = Field(
        description="Trades entered on a scan with confluence score >= 20"
    )
    items: List[TradeAttributionItem]


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


def _serialise_position_history(row: PositionHistory) -> Dict[str, Any]:
    return {
        "exchange_position_id": getattr(row, "exchange_position_id", None),
        "symbol": row.symbol,
        "side": row.side,
        "size": row.size,
        "entry_price": row.entry_price,
        "exit_price": row.exit_price,
        "pnl": row.pnl,
        "pnl_percent": row.pnl_percent,
        "leverage": row.leverage,
        "open_time": row.open_time,
        "close_time": row.close_time,
        "close_reason": row.close_reason,
        "contract_size": row.contract_size,
    }


def _serialise_order_history(row: OrderHistory) -> Dict[str, Any]:
    return {
        "exchange_order_id": getattr(row, "exchange_order_id", None),
        "symbol": row.symbol,
        "type": row.type,
        "side": row.side,
        "side_action": getattr(row, "side_action", None),
        "price": row.price,
        "amount": row.amount,
        "filled": row.filled,
        "filled_price": getattr(row, "filled_price", None),
        "cost": row.cost,
        "status": row.status,
        "timestamp": row.timestamp,
        "fee": getattr(row, "fee", None),
        "fee_currency": getattr(row, "fee_currency", None),
        "leverage": getattr(row, "leverage", None),
        "reduce_only": row.reduce_only,
    }


def _serialise_snapshot(row: PortfolioSnapshot) -> Dict[str, Any]:
    return {
        "total_balance_usd": row.total_balance_usd,
        "total_pnl_usd": row.total_pnl_usd,
        "open_positions": row.open_positions,
        "timestamp": row.timestamp,
    }


def _serialise_futures_account(row: FuturesAccountSnapshot) -> Dict[str, Any]:
    return {
        "settlement_asset": row.settlement_asset,
        "equity": row.equity,
        "available_balance": row.available_balance,
        "frozen_balance": row.frozen_balance,
        "cash_balance": row.cash_balance,
        "position_margin": row.position_margin,
        "unrealized_pnl": row.unrealized_pnl,
        "bonus": row.bonus,
        "available_cash": row.available_cash,
        "debt_amount": row.debt_amount,
        "source_ts": row.source_ts,
        "synced_at": row.synced_at,
    }


_PHASE2A_STREAMS = (
    "positions_history",
    "orders_history",
    "futures_account_assets",
    "funding",
    "futures_transfers",
    "deposits",
    "withdrawals",
)

_CAPITAL_FLOW_STREAMS = (
    "funding",
    "futures_transfers",
    "deposits",
    "withdrawals",
)


def _phase2a_default_coverage(stream: str) -> Dict[str, Any]:
    """Generic missing-stream coverage (stale / no_sync_state) for all Phase 2 streams."""
    return {
        "stream": stream,
        "status": "stale",
        "complete": False,
        "reason": "no_sync_state",
        "rows_fetched_total": 0,
        "source_total": 0,
        "cursor": None,
        "last_success_at": None,
        "last_attempt_at": None,
        "error_code": None,
        "error_message": None,
        "unrecoverable_gaps": [],
        "supported_by_exchange": True,
    }


def _coverage_from_sync_state(row: ExchangeSyncState) -> Dict[str, Any]:
    return {
        "stream": row.stream,
        "status": row.status,
        "complete": bool(row.complete),
        "reason": row.partial_reason,
        "oldest_source_ts": row.oldest_source_ts,
        "newest_source_ts": row.newest_source_ts,
        "rows_fetched_total": row.rows_fetched_total,
        "source_total": row.source_total,
        "cursor": row.cursor_json,
        "last_success_at": row.last_success_at,
        "last_attempt_at": row.last_attempt_at,
        "error_code": row.error_code,
        "error_message": row.error_message_redacted,
        "unrecoverable_gaps": row.unrecoverable_gaps_json or [],
        "supported_by_exchange": True,
    }


def _legacy_position_gaps(position_history: List[PositionHistory]) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    for row in position_history:
        if getattr(row, "exchange_position_id", None) is not None:
            continue
        gaps.append({
            "stream": "positions_history",
            "reason": "pre_phase_2a_missing_exchange_position_id",
            "position_history_id": row.id,
            "symbol": row.symbol,
            "close_time": row.close_time.isoformat() if row.close_time else None,
        })
    return gaps


def _merge_legacy_position_gaps(
    coverage: Dict[str, Any],
    position_history: List[PositionHistory],
) -> Dict[str, Any]:
    gaps = _legacy_position_gaps(position_history)
    if not gaps:
        return coverage
    merged = dict(coverage)
    merged["unrecoverable_gaps"] = list(merged.get("unrecoverable_gaps") or []) + gaps
    merged["complete"] = False
    if merged.get("status") == "fresh":
        merged["status"] = "partial"
    if not merged.get("reason"):
        merged["reason"] = "pre_phase_2a_missing_exchange_position_id"
    return merged


def _sync_list_from_mapping(
    sync: Optional[Dict[str, Dict[str, Any]]],
    *,
    position_history: Optional[List[PositionHistory]] = None,
    include_all_phase2a_streams: bool = True,
) -> List[SyncCoverageItem]:
    by_stream: Dict[str, Dict[str, Any]] = {}
    for stream, coverage in (sync or {}).items():
        row = dict(coverage)
        row.setdefault("stream", stream)
        row.setdefault("supported_by_exchange", True)
        by_stream[stream] = row
    streams = _PHASE2A_STREAMS if include_all_phase2a_streams else tuple(by_stream)
    for stream in streams:
        by_stream.setdefault(stream, _phase2a_default_coverage(stream))
    if position_history is not None and "positions_history" in by_stream:
        by_stream["positions_history"] = _merge_legacy_position_gaps(
            by_stream["positions_history"], position_history
        )
    return [SyncCoverageItem(**by_stream[stream]) for stream in streams if stream in by_stream]


async def _load_sync_coverage(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    *,
    position_history: Optional[List[PositionHistory]] = None,
) -> List[SyncCoverageItem]:
    result = await session.execute(
        select(ExchangeSyncState).where(
            ExchangeSyncState.user_id == user_id,
            ExchangeSyncState.exchange == exchange,
        )
    )
    return _sync_list_from_mapping(
        {row.stream: _coverage_from_sync_state(row) for row in result.scalars().all()},
        position_history=position_history,
    )


def _response_partial(sync: List[SyncCoverageItem]) -> bool:
    """Portfolio-level partial: core Phase 2A streams only (not capital-flow)."""
    return any(
        row.stream in {"positions_history", "orders_history", "futures_account_assets"}
        and not row.complete
        for row in sync
    )


def _capital_flow_response_partial(sync: List[SyncCoverageItem]) -> bool:
    """True only when a capital stream has been attempted and is meaningfully incomplete.

    Pure ``stale`` + ``no_sync_state`` placeholders (pre-sync defaults) do not
    drive ``partial=true``. Meaningful gaps: status in partial|unavailable|error,
    or any non-stale incomplete status.
    """
    for row in sync:
        status = (row.status or "").lower()
        if status in {"partial", "unavailable", "error"}:
            return True
        if status != "stale" and not row.complete:
            return True
    return False


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
    await session.execute(
        delete(PositionHistory).where(
            PositionHistory.user_id == current_user.id,
            PositionHistory.exchange == exchange_slug,
        )
    )
    await session.execute(
        delete(OrderHistory).where(
            OrderHistory.user_id == current_user.id,
            OrderHistory.exchange == exchange_slug,
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
    futures_account = await latest_futures_account_snapshot(
        session, current_user.id, exchange_slug
    )
    sync = _sync_list_from_mapping(data.get("sync"))
    return PortfolioResponse(
        exchange=exchange_slug,
        balances=[BalanceItem(**b) for b in data["balances"]],
        positions=[PositionItem(**p) for p in data["positions"]],
        trades=[TradeItem(**t) for t in data["trades"]],
        position_history=[PositionHistoryItem(**p) for p in data.get("position_history", [])],
        order_history=[OrderHistoryItem(**o) for o in data.get("order_history", [])],
        snapshot=SnapshotItem(**_serialise_snapshot(snapshot)) if snapshot else None,
        sync=sync,
        futures_account=(
            FuturesAccountItem(**_serialise_futures_account(futures_account))
            if futures_account
            else None
        ),
        partial=bool(data.get("partial", _response_partial(sync))),
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
    position_history = await _load_position_history(session, current_user.id, exchange_slug)
    order_history = await _load_order_history(session, current_user.id, exchange_slug)
    snapshot = await _get_latest_snapshot(session, current_user.id, exchange_slug)
    futures_account = await latest_futures_account_snapshot(
        session, current_user.id, exchange_slug
    )
    sync = await _load_sync_coverage(
        session,
        current_user.id,
        exchange_slug,
        position_history=position_history,
    )

    return PortfolioResponse(
        exchange=exchange_slug,
        balances=[BalanceItem(**_serialise_balance(b)) for b in balances],
        positions=[PositionItem(**_serialise_position(p)) for p in positions],
        trades=[TradeItem(**_serialise_trade(t)) for t in trades],
        position_history=[
            PositionHistoryItem(**_serialise_position_history(p)) for p in position_history
        ],
        order_history=[
            OrderHistoryItem(**_serialise_order_history(o)) for o in order_history
        ],
        snapshot=SnapshotItem(**_serialise_snapshot(snapshot)) if snapshot else None,
        sync=sync,
        futures_account=(
            FuturesAccountItem(**_serialise_futures_account(futures_account))
            if futures_account
            else None
        ),
        partial=_response_partial(sync),
        last_refreshed=_get_iso_ts(snapshot),
        stale=True,
    )


@router.get(
    "/{exchange}/sync-status",
    response_model=SyncStatusResponse,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_sync_status(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SyncStatusResponse:
    """Return cached Phase 2A stream coverage for this user/exchange only."""
    exchange_slug = _require_supported_exchange(exchange)
    position_history = await _load_position_history(session, current_user.id, exchange_slug)
    sync = await _load_sync_coverage(
        session,
        current_user.id,
        exchange_slug,
        position_history=position_history,
    )
    futures_account = await latest_futures_account_snapshot(
        session, current_user.id, exchange_slug
    )
    return SyncStatusResponse(
        exchange=exchange_slug,
        sync=sync,
        futures_account=(
            FuturesAccountItem(**_serialise_futures_account(futures_account))
            if futures_account
            else None
        ),
        partial=_response_partial(sync),
    )


@router.get(
    "/{exchange}/capital-flow",
    response_model=CapitalFlowResponse,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_capital_flow(
    exchange: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CapitalFlowResponse:
    """Return user-scoped capital-flow ledger rows with four-stream coverage.

    Cached only — no outbound exchange call. Rows sorted by occurred_at desc.
    """
    exchange_slug = _require_supported_exchange(exchange)

    result = await session.execute(
        select(CapitalFlowLedger)
        .where(
            CapitalFlowLedger.user_id == current_user.id,
            CapitalFlowLedger.exchange == exchange_slug,
        )
        .order_by(
            CapitalFlowLedger.occurred_at.desc().nullslast(),
            CapitalFlowLedger.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    rows = list(result.scalars().all())

    full_sync = await _load_sync_coverage(session, current_user.id, exchange_slug)
    by_stream = {s.stream: s for s in full_sync}
    capital_sync: List[SyncCoverageItem] = []
    for stream in _CAPITAL_FLOW_STREAMS:
        if stream in by_stream:
            capital_sync.append(by_stream[stream])
        else:
            capital_sync.append(SyncCoverageItem(**_phase2a_default_coverage(stream)))

    partial = _capital_flow_response_partial(capital_sync)
    return CapitalFlowResponse(
        exchange=exchange_slug,
        entries=[
            CapitalFlowEntryItem(
                id=r.id,
                entry_type=r.entry_type,
                exchange_entry_id=r.exchange_entry_id,
                asset=r.asset,
                amount=r.amount,
                signed_amount=r.signed_amount,
                status=r.status,
                occurred_at=r.occurred_at,
                source_updated_at=r.source_updated_at,
                synced_at=r.synced_at,
            )
            for r in rows
        ],
        sync=capital_sync,
        partial=partial,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{exchange}/position-alerts",
    response_model=PositionAlertsResponse,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_position_alerts(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PositionAlertsResponse:
    """Cross-reference each open position with the Miraj scan engine.

    For every open position, fetches the latest scan (cached or freshly run)
    and compares the position direction against QQE signals, market
    structure, and confluence direction. Also checks liquidation distance.

    Returns a list of at-risk positions with their alerts. Positions with no
    alerts are omitted.
    """
    exchange_slug = _require_supported_exchange(exchange)

    positions = await _load_positions(session, current_user.id, exchange_slug)
    if not positions:
        return PositionAlertsResponse(
            exchange=exchange_slug,
            total_alerts=0,
            danger_count=0,
            warning_count=0,
            positions=[],
        )

    # Convert ORM rows to plain dicts for the alert service
    position_dicts = [_serialise_position(p) for p in positions]

    from backend.services.position_alert_service import compute_position_alerts

    alert_items = await compute_position_alerts(position_dicts)

    danger_count = sum(
        1 for item in alert_items if item.get("max_severity") == "DANGER"
    )
    warning_count = sum(
        1 for item in alert_items if item.get("max_severity") == "WARNING"
    )

    return PositionAlertsResponse(
        exchange=exchange_slug,
        total_alerts=len(alert_items),
        danger_count=danger_count,
        warning_count=warning_count,
        positions=[PositionAlertItem(**item) for item in alert_items],
    )


# ── Dynamic DCA (Dollar Cost Averaging) ──────────────────────────────────────


class DcaEntryLevel(BaseModel):
    """A single RSI three-entry level."""
    entry: str
    trigger: str
    position_size_pct: str
    cumulative_pct: str
    status: str = Field(description="filled or pending")
    trigger_type: str = Field(description="rsi or zone")
    rsi_target: int
    level_price: Optional[float] = None


class DcaZone(BaseModel):
    """The OTE / demand zone where DCA entries should be placed."""
    low: float
    high: float
    label: str


class DcaRecommendation(BaseModel):
    """Dynamic DCA recommendation for a single open position."""
    symbol: str
    position_side: str
    entry_price: float
    mark_price: float
    pnl: float
    pnl_percent: float
    leverage: float
    recommendation: str = Field(description="ADD / HOLD / REDUCE / CLOSE")
    reason: str
    confidence: str = Field(description="LOW / MEDIUM / HIGH / CRITICAL")
    rsi_current: Optional[float] = None
    rsi_entries: List[DcaEntryLevel] = []
    next_entry: Optional[DcaEntryLevel] = None
    dca_zone: Optional[DcaZone] = None
    tp_levels: List[float] = []
    risk_rules: List[str] = []
    future_add_triggers: List[str] = []
    action_items: List[str] = []


class DcaResponse(BaseModel):
    """Response for GET /api/v1/portfolio/{exchange}/dca."""
    exchange: str
    total_positions: int
    add_count: int
    reduce_count: int
    close_count: int
    hold_count: int
    positions: List[DcaRecommendation]


@router.get(
    "/{exchange}/dca",
    response_model=DcaResponse,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_dca_recommendations(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DcaResponse:
    """Dynamic DCA recommendations for open positions.

    For every open position, fetches the latest Miraj pair analysis (cached or
    freshly run) and computes a DCA recommendation:

    * **ADD** — price in OTE/demand zone + QQE aligned + RSI oversold.
      Suggests next entry size per Miraj's 20/20/60 three-entry system.
    * **HOLD** — position fine, no action needed.
    * **REDUCE** — QQE flipped against, at TP1, PnL >= 100%, or below BMSB.
    * **CLOSE** — confluence opposed with 3+ conflicts, or liquidation < 2%.

    Returns adaptive RSI entry ladder, future ADD triggers, and action items.
    """
    exchange_slug = _require_supported_exchange(exchange)

    positions = await _load_positions(session, current_user.id, exchange_slug)
    if not positions:
        return DcaResponse(
            exchange=exchange_slug,
            total_positions=0,
            add_count=0,
            reduce_count=0,
            close_count=0,
            hold_count=0,
            positions=[],
        )

    position_dicts = [_serialise_position(p) for p in positions]

    from backend.services.dca_service import compute_dca_recommendations

    dca_items = await compute_dca_recommendations(position_dicts)

    add_count = sum(1 for i in dca_items if i["recommendation"] == "ADD")
    reduce_count = sum(1 for i in dca_items if i["recommendation"] == "REDUCE")
    close_count = sum(1 for i in dca_items if i["recommendation"] == "CLOSE")
    hold_count = sum(1 for i in dca_items if i["recommendation"] == "HOLD")

    return DcaResponse(
        exchange=exchange_slug,
        total_positions=len(dca_items),
        add_count=add_count,
        reduce_count=reduce_count,
        close_count=close_count,
        hold_count=hold_count,
        positions=[DcaRecommendation(**item) for item in dca_items],
    )


# ── Position Desk (verdict-joined positions) ─────────────────────────────


class PositionDeskRow(BaseModel):
    """One open position joined with its scan verdict and DCA ruling."""

    symbol: str
    scan_symbol: str
    side: str
    size: Optional[float] = None
    entry_price: Optional[float] = None
    mark_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    leverage: Optional[float] = None
    liquidation_price: Optional[float] = None
    liq_distance_pct: Optional[float] = None
    verdict: Optional[Dict[str, Any]] = None
    regime: Optional[str] = None
    regime_band_low: Optional[float] = None
    regime_band_high: Optional[float] = None
    alignment: str
    recommendation: str
    confidence: Optional[str] = None
    ruling: str
    detail: Optional[str] = None
    add_zone: Optional[Dict[str, Any]] = None
    next_entry: Optional[Dict[str, Any]] = None
    tp_levels: List[float] = Field(default_factory=list)
    action_items: List[str] = Field(default_factory=list)
    next_review: Optional[str] = None


class PositionDeskResponse(BaseModel):
    """Verdict-joined view of all open positions for one exchange."""

    exchange: str
    total_positions: int
    positions: List[PositionDeskRow]


@router.get(
    "/{exchange}/position-desk",
    response_model=PositionDeskResponse,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_position_desk(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PositionDeskResponse:
    """Join every open position with its live verdict and DCA ruling.

    The portfolio page's decision layer: for each position — the typed scan
    verdict, weekly-regime alignment, the DCA engine's recommendation, and a
    one-line mechanical ruling ("Reduce — wrong side of the weekly band.").
    """
    exchange_slug = _require_supported_exchange(exchange)

    positions = await _load_positions(session, current_user.id, exchange_slug)
    if not positions:
        return PositionDeskResponse(
            exchange=exchange_slug, total_positions=0, positions=[]
        )

    position_dicts = [_serialise_position(p) for p in positions]

    from backend.services.position_desk_service import compute_position_desk

    desk_rows = await compute_position_desk(position_dicts)

    return PositionDeskResponse(
        exchange=exchange_slug,
        total_positions=len(desk_rows),
        positions=[PositionDeskRow(**row) for row in desk_rows],
    )


@router.get(
    "/{exchange}/trade-attribution",
    response_model=TradeAttributionResponse,
    responses={
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_trade_attribution(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TradeAttributionResponse:
    """Link each closed position to the Miraj scan that preceded its entry.

    For every closed position in :class:`PositionHistory`, finds the nearest
    :class:`Analysis` (scan) for that symbol whose ``created_at`` is at or
    before the position's ``open_time``, and returns the confluence score,
    inferred trade direction, and per-TF QQE signals of that scan.

    This shows **which** confluence score led to each trade — useful for
    evaluating whether high-score signals actually produce profitable trades.

    The endpoint reads purely from cache tables (no exchange API call) and
    requires ccxt to be installed so the exchange slug is validated.
    """
    exchange_slug = _require_supported_exchange(exchange)

    from backend.services.scan_attribution_service import link_positions_to_scans

    items = await link_positions_to_scans(
        session, current_user.id, exchange_slug
    )
    high_confidence = sum(
        1 for it in items if it.get("scan_score") is not None and it["scan_score"] >= 20
    )
    return TradeAttributionResponse(
        exchange=exchange_slug,
        total_trades=len(items),
        high_confidence_trades=high_confidence,
        items=[TradeAttributionItem(**it) for it in items],
    )


@router.get(
    "/{exchange}/history",
    response_model=HistoryResponse,
    responses={
        400: {"model": PortfolioErrorResponse, "description": "No stored keys"},
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        429: {"model": PortfolioErrorResponse, "description": "Rate limited"},
        502: {"model": PortfolioErrorResponse, "description": "Exchange error"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_portfolio_history(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HistoryResponse:
    """Fetch fresh position history + order history from the exchange.

    Unlike ``GET /{exchange}``, this endpoint always makes a live exchange
    call (no cache) so the user sees the most recent closed positions and
    orders. Intended for the "Position History" and "Order History" tabs.
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

    # 2. Fetch live history data
    try:
        data = await fetch_history(
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
        raise _map_exchange_error(exc, action="fetch history") from exc

    futures_account = await latest_futures_account_snapshot(
        session, current_user.id, exchange_slug
    )
    sync = _sync_list_from_mapping(data.get("sync"), include_all_phase2a_streams=False)
    return HistoryResponse(
        exchange=exchange_slug,
        position_history=[
            PositionHistoryItem(**p) for p in data.get("position_history", [])
        ],
        order_history=[
            OrderHistoryItem(**o) for o in data.get("order_history", [])
        ],
        sync=sync,
        futures_account=(
            FuturesAccountItem(**_serialise_futures_account(futures_account))
            if futures_account
            else None
        ),
        partial=bool(data.get("partial", _response_partial(sync))),
    )


@router.post(
    "/{exchange}/history",
    response_model=HistoryResponse,
    responses={
        400: {"model": PortfolioErrorResponse, "description": "No stored keys"},
        404: {"model": PortfolioErrorResponse, "description": "Unsupported exchange"},
        429: {"model": PortfolioErrorResponse, "description": "Rate limited"},
        502: {"model": PortfolioErrorResponse, "description": "Exchange error"},
        501: {"model": PortfolioErrorResponse, "description": "ccxt not installed"},
    },
)
async def get_exchange_history(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HistoryResponse:
    """Fetch position history + order history from the exchange, persist to
    cache tables, and return the freshest data.

    Unlike ``POST /refresh`` this endpoint only fetches the two historical
    lists (no balances / open positions / trades), making it lighter for
    tab-switching on the frontend.
    """
    exchange_slug = _require_supported_exchange(exchange)

    # 1. Get exchange instance
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

    # 2. Fetch history from exchange
    try:
        data = await fetch_history(
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
        raise _map_exchange_error(exc, action="history") from exc

    # 3. Persist both lists to cache tables (dedup-aware)
    now = datetime.utcnow()
    await _persist_history_data(session, current_user.id, exchange_slug, data, now)
    await session.commit()

    futures_account = await latest_futures_account_snapshot(
        session, current_user.id, exchange_slug
    )
    sync = _sync_list_from_mapping(data.get("sync"), include_all_phase2a_streams=False)
    return HistoryResponse(
        exchange=exchange_slug,
        position_history=[
            PositionHistoryItem(**p) for p in data.get("position_history", [])
        ],
        order_history=[
            OrderHistoryItem(**o) for o in data.get("order_history", [])
        ],
        sync=sync,
        futures_account=(
            FuturesAccountItem(**_serialise_futures_account(futures_account))
            if futures_account
            else None
        ),
        partial=bool(data.get("partial", _response_partial(sync))),
    )


# ── DB persistence helpers ───────────────────────────────────────────────────


async def _persist_history_data(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    data: Dict[str, List[Dict[str, Any]]],
    now: datetime,
) -> None:
    """Persist position_history and order_history from a history-only fetch.

    Uses the same dedup-aware upsert logic as ``_persist_portfolio_data``
    but only handles the two history tables — no balances / positions /
    trades / snapshot.
    """
    await persist_phase2a_sync_payload(session, user_id, exchange, data, now)
    await persist_capital_flow_payload(session, user_id, exchange, data, now)


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

    await persist_phase2a_sync_payload(session, user_id, exchange, data, now)
    await persist_capital_flow_payload(session, user_id, exchange, data, now)

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


async def _load_position_history(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[PositionHistory]:
    result = await session.execute(
        select(PositionHistory)
        .where(
            PositionHistory.user_id == user_id,
            PositionHistory.exchange == exchange,
        )
        .order_by(PositionHistory.close_time.desc().nullslast())
        .limit(200)
    )
    return list(result.scalars().all())


async def _load_order_history(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[OrderHistory]:
    result = await session.execute(
        select(OrderHistory)
        .where(
            OrderHistory.user_id == user_id,
            OrderHistory.exchange == exchange,
        )
        .order_by(OrderHistory.timestamp.desc())
        .limit(200)
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
