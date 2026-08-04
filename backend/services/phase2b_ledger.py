"""Phase 2B capital-flow ledger coerce + idempotent persist."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import CapitalFlowLedger, ExchangeSyncState

ENTRY_TYPES = ("funding", "futures_transfer", "deposit", "withdrawal")

STREAM_TO_ENTRY_TYPE = {
    "funding": "funding",
    "futures_transfers": "futures_transfer",
    "deposits": "deposit",
    "withdrawals": "withdrawal",
}
ENTRY_STREAMS = tuple(STREAM_TO_ENTRY_TYPE.keys())


def _mexc_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
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


def _redact_error(message: str) -> str:
    """Strip known secret-like tokens from error text before persist."""
    redacted = str(message).replace("synthetic-key", "[redacted]")
    for token in ("apiKey", "secret", "Authorization"):
        redacted = redacted.replace(token, "[redacted]")
    return redacted


def synthetic_exchange_entry_id(
    entry_type: str,
    asset: str,
    amount: Optional[float],
    occurred_at: Optional[datetime],
    *,
    symbol: str = "",
    extra: str = "",
) -> str:
    """Deterministic id for source rows that lack a stable exchange id.

    Funding rows often share asset+timestamp across symbols; include ``symbol``
    (and optional ``extra`` such as positionType) so concurrent settlements do
    not collapse into one ledger row.
    """
    ts = occurred_at.isoformat() if occurred_at else ""
    amt = "" if amount is None else f"{amount:.12g}"
    digest = hashlib.sha256(
        f"{entry_type}|{asset}|{amt}|{ts}|{symbol}|{extra}".encode("utf-8")
    ).hexdigest()
    return f"synth:{digest[:48]}"


def _ensure_source_id(row: Dict[str, Any], *, symbol: str = "", extra: str = "") -> Dict[str, Any]:
    if row.get("exchange_entry_id"):
        row["exchange_entry_id"] = str(row["exchange_entry_id"])[:128]
        return row
    row["exchange_entry_id"] = synthetic_exchange_entry_id(
        row["entry_type"],
        row["asset"],
        row.get("amount"),
        row.get("occurred_at"),
        symbol=symbol or str(row.get("symbol") or ""),
        extra=extra or str(row.get("position_type") or row.get("positionType") or ""),
    )
    return row


def _raw_json(raw: Dict[str, Any]) -> str:
    return json.dumps(raw, default=str, separators=(",", ":"))


def coerce_funding_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("entry_type") == "funding" and "signed_amount" in raw:
        return _ensure_source_id(dict(raw))
    amount = _safe_float(raw.get("funding") if raw.get("funding") is not None else raw.get("amount"))
    occurred = _mexc_datetime(raw.get("settleTime") or raw.get("createTime") or raw.get("timestamp"))
    source_id = raw.get("id") or raw.get("fundingRecordId")
    symbol = str(raw.get("symbol") or "")
    position_type = str(raw.get("positionType") if raw.get("positionType") is not None else raw.get("position_type") or "")
    # funding already signed in MEXC samples; keep exchange sign
    signed = amount
    row = {
        "entry_type": "funding",
        "exchange_entry_id": str(source_id) if source_id is not None else None,
        "asset": str(raw.get("currency") or raw.get("asset") or "USDT"),
        "amount": abs(amount) if amount is not None else None,
        "signed_amount": signed,
        "status": str(raw.get("state") or raw.get("status") or "") or None,
        "occurred_at": occurred,
        "source_updated_at": _mexc_datetime(raw.get("updateTime")) or occurred,
        "raw_json": _raw_json(raw),
        "symbol": symbol or None,
        "position_type": position_type or None,
    }
    return _ensure_source_id(row, symbol=symbol, extra=position_type)


def coerce_futures_transfer_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("entry_type") == "futures_transfer" and "signed_amount" in raw:
        return _ensure_source_id(dict(raw))
    amount = _safe_float(raw.get("amount"))
    t = str(raw.get("type") or raw.get("transferType") or "").upper()
    into_futures = t in {"IN", "1", "TRANSFER_IN", "INCOME", "DEPOSIT"}
    out_futures = t in {"OUT", "2", "TRANSFER_OUT", "OUTCOME", "WITHDRAW"}
    if amount is None:
        signed = None
    elif into_futures:
        signed = abs(amount)
    elif out_futures:
        signed = -abs(amount)
    else:
        # unknown type: preserve numeric sign if any, else +abs
        signed = amount
    occurred = _mexc_datetime(raw.get("createTime") or raw.get("timestamp"))
    source_id = raw.get("id") or raw.get("tranId") or raw.get("transferId")
    row = {
        "entry_type": "futures_transfer",
        "exchange_entry_id": str(source_id) if source_id is not None else None,
        "asset": str(raw.get("currency") or raw.get("asset") or "USDT"),
        "amount": abs(amount) if amount is not None else None,
        "signed_amount": signed,
        "status": str(raw.get("state") or raw.get("status") or "") or None,
        "occurred_at": occurred,
        "source_updated_at": _mexc_datetime(raw.get("updateTime")) or occurred,
        "raw_json": _raw_json(raw),
    }
    return _ensure_source_id(row)


def coerce_deposit_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("entry_type") == "deposit" and "signed_amount" in raw:
        return _ensure_source_id(dict(raw))
    amount = _safe_float(raw.get("amount"))
    occurred = _mexc_datetime(raw.get("timestamp") or raw.get("createTime"))
    source_id = raw.get("id") or raw.get("txid")
    row = {
        "entry_type": "deposit",
        "exchange_entry_id": str(source_id) if source_id is not None else None,
        "asset": str(raw.get("currency") or raw.get("asset") or "USDT"),
        "amount": abs(amount) if amount is not None else None,
        "signed_amount": abs(amount) if amount is not None else None,
        "status": str(raw.get("status") or "") or None,
        "occurred_at": occurred,
        "source_updated_at": occurred,
        "raw_json": _raw_json(raw),
    }
    return _ensure_source_id(row)


def coerce_withdrawal_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("entry_type") == "withdrawal" and "signed_amount" in raw:
        return _ensure_source_id(dict(raw))
    amount = _safe_float(raw.get("amount"))
    occurred = _mexc_datetime(raw.get("timestamp") or raw.get("createTime"))
    source_id = raw.get("id") or raw.get("txid")
    row = {
        "entry_type": "withdrawal",
        "exchange_entry_id": str(source_id) if source_id is not None else None,
        "asset": str(raw.get("currency") or raw.get("asset") or "USDT"),
        "amount": abs(amount) if amount is not None else None,
        "signed_amount": -abs(amount) if amount is not None else None,
        "status": str(raw.get("status") or "") or None,
        "occurred_at": occurred,
        "source_updated_at": occurred,
        "raw_json": _raw_json(raw),
    }
    return _ensure_source_id(row)


_COERCERS = {
    "funding": coerce_funding_row,
    "futures_transfers": coerce_futures_transfer_row,
    "deposits": coerce_deposit_row,
    "withdrawals": coerce_withdrawal_row,
}


async def persist_capital_flow_payload(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    payload: Dict[str, Any],
    now: datetime,
) -> None:
    for stream, coercer in _COERCERS.items():
        rows = payload.get(stream) or []
        await _upsert_entries(session, user_id, exchange, [coercer(r) for r in rows], now)
    for stream, coverage in (payload.get("sync") or {}).items():
        if stream in ENTRY_STREAMS or stream in STREAM_TO_ENTRY_TYPE:
            await _upsert_sync_state(session, user_id, exchange, stream, coverage, now)


async def _upsert_entries(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    rows: Iterable[Dict[str, Any]],
    now: datetime,
) -> None:
    seen: set[str] = set()
    for row in rows:
        source_id = row.get("exchange_entry_id")
        if not source_id:
            continue
        key = f"{row['entry_type']}:{source_id}"
        if key in seen:
            continue
        seen.add(key)
        existing = await session.scalar(
            select(CapitalFlowLedger).where(
                CapitalFlowLedger.user_id == user_id,
                CapitalFlowLedger.exchange == exchange,
                CapitalFlowLedger.entry_type == row["entry_type"],
                CapitalFlowLedger.exchange_entry_id == str(source_id),
            )
        )
        target = existing or CapitalFlowLedger(user_id=user_id, exchange=exchange)
        target.entry_type = row["entry_type"]
        target.exchange_entry_id = str(source_id)
        target.asset = row["asset"]
        target.amount = row.get("amount")
        target.signed_amount = row.get("signed_amount")
        target.status = row.get("status")
        target.occurred_at = row.get("occurred_at")
        target.source_updated_at = row.get("source_updated_at")
        target.synced_at = now
        target.raw_json = row.get("raw_json")
        session.add(target)


async def _upsert_sync_state(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    stream: str,
    coverage: Dict[str, Any],
    now: datetime,
) -> None:
    """Match phase2a_sync._upsert_sync_state: last_success_at only when complete."""
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
        err = coverage.get("error_message")
        target.error_message_redacted = _redact_error(err) if err is not None else None
    target.updated_at = now
    session.add(target)
