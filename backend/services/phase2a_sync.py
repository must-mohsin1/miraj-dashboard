"""Phase 2A MEXC sync-state and source-id upsert helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ExchangeSyncState, FuturesAccountSnapshot, OrderHistory, PositionHistory


def _mexc_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.utcfromtimestamp(int(value) / 1000.0)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_position(row: Dict[str, Any]) -> Dict[str, Any]:
    if "side" in row:
        return row
    close_time = _mexc_datetime(row.get("updateTime"))
    profit_ratio = _safe_float(row.get("profitRatio")) or 0.0
    pnl = _safe_float(row.get("closeProfitLoss")) or 0.0
    return {
        "exchange_position_id": str(row.get("positionId")) if row.get("positionId") is not None else None,
        "symbol": str(row.get("symbol", "")).replace("_", ""),
        "side": "long" if str(row.get("positionType", "1")) == "1" else "short",
        "size": _safe_float(row.get("closeVol")) or 0.0,
        "entry_price": _safe_float(row.get("holdAvgPrice")) or 0.0,
        "exit_price": _safe_float(row.get("closeAvgPrice")) or 0.0,
        "pnl": pnl,
        "pnl_percent": profit_ratio * 100,
        "reported_pnl": pnl,
        "reported_roi_pct": profit_ratio * 100,
        "leverage": _safe_float(row.get("leverage")) or 1.0,
        "open_time": _mexc_datetime(row.get("createTime")),
        "close_time": close_time,
        "close_reason": "closed",
        "contract_size": 1.0,
        "source_state": str(row.get("state")) if row.get("state") is not None else None,
        "source_updated_at": close_time,
    }


def _coerce_order(row: Dict[str, Any]) -> Dict[str, Any]:
    if "type" in row:
        return row
    side_map = {"1": ("buy", "Open Long"), "2": ("sell", "Close Long"), "3": ("sell", "Open Short"), "4": ("buy", "Close Short")}
    side, side_action = side_map.get(str(row.get("side", "")), ("", str(row.get("side", ""))))
    filled = _safe_float(row.get("dealVol")) or 0.0
    filled_price = _safe_float(row.get("dealAvgPrice")) or 0.0
    return {
        "exchange_order_id": str(row.get("orderId")) if row.get("orderId") is not None else None,
        "symbol": str(row.get("symbol", "")).replace("_", ""),
        "type": "limit" if str(row.get("orderType", "1")) == "1" else "market",
        "side": side,
        "side_action": side_action,
        "price": _safe_float(row.get("price")) or 0.0,
        "amount": _safe_float(row.get("vol")) or 0.0,
        "filled": filled,
        "filled_price": filled_price,
        "cost": filled * filled_price,
        "status": "filled" if str(row.get("state", "3")) == "3" else str(row.get("state", "")),
        "timestamp": _mexc_datetime(row.get("createTime")) or datetime.utcnow(),
        "fee": _safe_float(row.get("fee")) or 0.0,
        "fee_currency": row.get("feeCurrency") or "USDT",
        "leverage": _safe_float(row.get("leverage")) or 1.0,
        "reduce_only": 1 if str(row.get("openType", "")) == "2" else 0,
        "source_updated_at": _mexc_datetime(row.get("updateTime")),
    }


def _coerce_futures_account(row: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    if "settlement_asset" in row:
        return row
    return {
        "settlement_asset": row.get("currency") or row.get("asset") or "USDT",
        "equity": _safe_float(row.get("equity")),
        "available_balance": _safe_float(row.get("availableBalance")),
        "frozen_balance": _safe_float(row.get("frozenBalance")),
        "cash_balance": _safe_float(row.get("cashBalance")),
        "position_margin": _safe_float(row.get("positionMargin")),
        "unrealized_pnl": _safe_float(row.get("unrealized")),
        "bonus": _safe_float(row.get("bonus")),
        "available_cash": _safe_float(row.get("availableCash")),
        "debt_amount": _safe_float(row.get("debtAmount")),
        "source_ts": _mexc_datetime(row.get("updateTime") or row.get("timestamp")) or now,
    }


async def persist_phase2a_sync_payload(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    payload: Dict[str, Any],
    now: datetime,
) -> None:
    """Persist Phase 2A source-ID streams idempotently for one user/exchange."""
    await _upsert_positions(session, user_id, exchange, payload.get("position_history", []), now)
    await _upsert_orders(session, user_id, exchange, payload.get("order_history", []), now)
    await _upsert_futures_account(session, user_id, exchange, payload.get("futures_account"), now)
    for stream, coverage in (payload.get("sync") or {}).items():
        await _upsert_sync_state(session, user_id, exchange, stream, coverage, now)


async def latest_futures_account_snapshot(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Optional[FuturesAccountSnapshot]:
    """Latest futures snapshot, preferring preferred settlement assets (USDT…).

    Avoids returning a dust STETH zero-wallet when a newer/better USDT row exists
    at the same freshness window.
    """
    from backend.services.futures_settlement import _EQUITY_EPS, _pref_rank

    result = await session.execute(
        select(FuturesAccountSnapshot)
        .where(FuturesAccountSnapshot.user_id == user_id, FuturesAccountSnapshot.exchange == exchange)
        .order_by(FuturesAccountSnapshot.source_ts.desc(), FuturesAccountSnapshot.id.desc())
        .limit(40)
    )
    rows = list(result.scalars().all())
    if not rows:
        return None
    newest_ts = rows[0].source_ts
    # Consider the latest sync batch (same source_ts) first, then fall back.
    same_ts = [r for r in rows if r.source_ts == newest_ts] or rows[:1]

    def _score(r: FuturesAccountSnapshot) -> tuple:
        eq = abs(float(r.equity or 0.0))
        nonzero = 0 if eq > _EQUITY_EPS else 1
        return (nonzero, _pref_rank((r.settlement_asset or "").upper()), -eq)

    same_ts.sort(key=_score)
    return same_ts[0]


async def _upsert_positions(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    rows: Iterable[Dict[str, Any]],
    now: datetime,
) -> None:
    for row in rows:
        row = _coerce_position(row)
        source_id = row.get("exchange_position_id")
        existing = None
        if source_id:
            existing = await session.scalar(
                select(PositionHistory).where(
                    PositionHistory.user_id == user_id,
                    PositionHistory.exchange == exchange,
                    PositionHistory.exchange_position_id == str(source_id),
                )
            )
        if existing is None and not source_id:
            existing = await session.scalar(
                select(PositionHistory).where(
                    PositionHistory.user_id == user_id,
                    PositionHistory.exchange == exchange,
                    PositionHistory.symbol == row["symbol"],
                    PositionHistory.close_time == row.get("close_time"),
                )
            )
        target = existing or PositionHistory(user_id=user_id, exchange=exchange)
        target.exchange_position_id = str(source_id) if source_id is not None else None
        target.symbol = row["symbol"]
        target.side = row["side"]
        target.size = row["size"]
        target.entry_price = row["entry_price"]
        target.exit_price = row.get("exit_price", 0.0)
        target.pnl = row["pnl"]
        target.pnl_percent = row.get("pnl_percent", 0.0)
        target.reported_pnl = row.get("reported_pnl", row["pnl"])
        target.reported_roi_pct = row.get("reported_roi_pct", row.get("pnl_percent", 0.0))
        target.leverage = row.get("leverage", 1.0)
        target.open_time = row.get("open_time")
        target.close_time = row.get("close_time")
        target.close_reason = row.get("close_reason")
        target.contract_size = row.get("contract_size", 1.0)
        target.source_state = row.get("source_state")
        target.source_updated_at = row.get("source_updated_at")
        target.synced_at = now
        target.updated_at = now
        session.add(target)


async def _upsert_orders(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    rows: Iterable[Dict[str, Any]],
    now: datetime,
) -> None:
    seen_source_ids: set[str] = set()
    for row in rows:
        row = _coerce_order(row)
        source_id = row.get("exchange_order_id")
        if source_id and str(source_id) in seen_source_ids:
            continue
        if source_id:
            seen_source_ids.add(str(source_id))
        existing = None
        if source_id:
            existing = await session.scalar(
                select(OrderHistory).where(
                    OrderHistory.user_id == user_id,
                    OrderHistory.exchange == exchange,
                    OrderHistory.exchange_order_id == str(source_id),
                )
            )
        if existing is None and not source_id:
            existing = await session.scalar(
                select(OrderHistory).where(
                    OrderHistory.user_id == user_id,
                    OrderHistory.exchange == exchange,
                    OrderHistory.symbol == row["symbol"],
                    OrderHistory.timestamp == row["timestamp"],
                    OrderHistory.side == row["side"],
                    OrderHistory.price == row["price"],
                )
            )
        target = existing or OrderHistory(user_id=user_id, exchange=exchange)
        target.exchange_order_id = str(source_id) if source_id is not None else None
        target.symbol = row["symbol"]
        target.type = row["type"]
        target.side = row["side"]
        target.side_action = row.get("side_action")
        target.price = row["price"]
        target.amount = row["amount"]
        target.filled = row.get("filled", 0.0)
        target.filled_price = row.get("filled_price")
        target.cost = row.get("cost", 0.0)
        target.status = row["status"]
        target.timestamp = row["timestamp"]
        target.fee = row.get("fee")
        target.fee_currency = row.get("fee_currency")
        target.leverage = row.get("leverage")
        target.reduce_only = row.get("reduce_only")
        target.source_updated_at = row.get("source_updated_at")
        target.synced_at = now
        target.updated_at = now
        session.add(target)


async def _upsert_futures_account(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    row: Optional[Dict[str, Any]],
    now: datetime,
) -> None:
    if not row:
        return
    row = _coerce_futures_account(row, now)
    source_ts = row.get("source_ts") or now
    settlement_asset = row.get("settlement_asset") or "USDT"
    target = await session.scalar(
        select(FuturesAccountSnapshot).where(
            FuturesAccountSnapshot.user_id == user_id,
            FuturesAccountSnapshot.exchange == exchange,
            FuturesAccountSnapshot.settlement_asset == settlement_asset,
            FuturesAccountSnapshot.source_ts == source_ts,
        )
    )
    target = target or FuturesAccountSnapshot(user_id=user_id, exchange=exchange, settlement_asset=settlement_asset, source_ts=source_ts)
    for field in (
        "equity",
        "available_balance",
        "frozen_balance",
        "cash_balance",
        "position_margin",
        "unrealized_pnl",
        "bonus",
        "available_cash",
        "debt_amount",
    ):
        setattr(target, field, row.get(field))
    target.synced_at = now
    session.add(target)


async def _upsert_sync_state(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    stream: str,
    coverage: Dict[str, Any],
    now: datetime,
) -> None:
    target = await session.scalar(
        select(ExchangeSyncState).where(
            ExchangeSyncState.user_id == user_id,
            ExchangeSyncState.exchange == exchange,
            ExchangeSyncState.stream == stream,
        )
    )
    target = target or ExchangeSyncState(user_id=user_id, exchange=exchange, stream=stream)
    complete = bool(coverage.get("complete"))
    target.status = coverage.get("status") or ("fresh" if complete else "partial")
    target.cursor_json = coverage.get("cursor")
    target.oldest_source_ts = coverage.get("oldest_source_ts")
    target.newest_source_ts = coverage.get("newest_source_ts")
    target.rows_fetched_total = int(coverage.get("rows_fetched_total") or 0)
    target.source_total = coverage.get("source_total")
    target.complete = complete
    target.partial_reason = coverage.get("reason")
    target.unrecoverable_gaps_json = coverage.get("unrecoverable_gaps") or []
    target.last_attempt_at = now
    if complete:
        target.last_success_at = now
        target.error_code = None
        target.error_message_redacted = None
    else:
        target.error_code = coverage.get("error_code")
        target.error_message_redacted = coverage.get("error_message")
    target.updated_at = now
    session.add(target)
