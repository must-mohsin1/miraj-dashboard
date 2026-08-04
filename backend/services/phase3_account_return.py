"""Phase 3 cash-flow-adjusted account return from futures equity + capital ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import CapitalFlowLedger, ExchangeSyncState, FuturesAccountSnapshot

# External capital only — funding is reflected in equity change, not as inflow.
EXTERNAL_ENTRY_TYPES = frozenset({"deposit", "withdrawal", "futures_transfer"})
EXTERNAL_STREAMS = ("deposits", "withdrawals", "futures_transfers")
_SATISFIED_UNAVAILABLE = frozenset({"unavailable"})
_BLOCKING_STATUSES = frozenset({"partial", "error", "stale", "not_enabled_phase_2b"})


def _iso(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.isoformat() + "Z"
    return ts.isoformat()


async def compute_account_return(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Dict[str, Any]:
    """Return cash-flow-adjusted account return or a fail-closed unavailable payload.

    Shape when available:
      account_return_pct, net_account_profit_usd, opening_equity, ending_equity,
      net_external_flows, opening_source_ts, ending_source_ts, basis, reason=None

    Shape when unavailable:
      account_return_pct=None, net_account_profit_usd=None, reason=<code>, ...
    """
    coverage = await _external_coverage(session, user_id, exchange)
    if not coverage["ok"]:
        return _unavailable(coverage["reason"], coverage_detail=coverage)

    snapshots = await _load_equity_snapshots(session, user_id, exchange)
    if len(snapshots) < 2:
        if not snapshots or snapshots[0].equity is None:
            return _unavailable("opening_equity_missing", coverage_detail=coverage)
        return _unavailable("insufficient_equity_snapshots", coverage_detail=coverage)

    opening = snapshots[0]
    ending = snapshots[-1]
    if opening.equity is None:
        return _unavailable("opening_equity_missing", coverage_detail=coverage)
    if ending.equity is None:
        return _unavailable("ending_equity_missing", coverage_detail=coverage)
    if opening.source_ts >= ending.source_ts and opening.id == ending.id:
        return _unavailable("insufficient_equity_snapshots", coverage_detail=coverage)

    opening_equity = float(opening.equity)
    ending_equity = float(ending.equity)
    if opening_equity == 0.0:
        return _unavailable(
            "opening_equity_zero",
            coverage_detail=coverage,
            opening_equity=0.0,
            ending_equity=ending_equity,
            opening_source_ts=opening.source_ts,
            ending_source_ts=ending.source_ts,
        )

    flows = await _load_external_flows(
        session,
        user_id,
        exchange,
        opening.source_ts,
        ending.source_ts,
    )
    net_external = sum(float(f.signed_amount or 0.0) for f in flows)

    net_profit = ending_equity - opening_equity - net_external
    # Cash-flow-adjusted simple return (percent points).
    return_frac = (ending_equity - net_external) / opening_equity - 1.0
    return_pct = return_frac * 100.0

    return {
        "account_return_pct": round(return_pct, 4),
        "account_return_pct_reason": None,
        "net_account_profit_usd": round(net_profit, 4),
        "net_account_profit_usd_reason": None,
        "opening_equity": round(opening_equity, 4),
        "ending_equity": round(ending_equity, 4),
        "net_external_flows": round(net_external, 4),
        "opening_source_ts": opening.source_ts,
        "ending_source_ts": ending.source_ts,
        "external_flow_count": len(flows),
        "basis": "cash_flow_adjusted_futures_equity",
        "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
        "complete": True,
        "reason": None,
        "coverage": coverage,
    }


async def _external_coverage(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Dict[str, Any]:
    result = await session.execute(
        select(ExchangeSyncState).where(
            ExchangeSyncState.user_id == user_id,
            ExchangeSyncState.exchange == exchange,
            ExchangeSyncState.stream.in_(EXTERNAL_STREAMS),
        )
    )
    by_stream = {row.stream: row for row in result.scalars().all()}
    details: Dict[str, Any] = {}
    blocking: List[str] = []

    for stream in EXTERNAL_STREAMS:
        row = by_stream.get(stream)
        if row is None:
            details[stream] = {"status": "missing", "complete": False}
            blocking.append(stream)
            continue
        status = (row.status or "").lower()
        complete = bool(row.complete)
        details[stream] = {
            "status": status,
            "complete": complete,
            "reason": row.partial_reason,
        }
        if complete:
            continue
        if status in _SATISFIED_UNAVAILABLE:
            # Unsupported stream → empty ledger, still OK for external-flow truth.
            continue
        if status in _BLOCKING_STATUSES or not complete:
            blocking.append(stream)

    if blocking:
        # Prefer incomplete over missing for messaging.
        if any(details[s]["status"] == "missing" for s in blocking):
            reason = "capital_history_missing"
        else:
            reason = "capital_history_incomplete"
        return {"ok": False, "reason": reason, "streams": details, "blocking": blocking}

    return {"ok": True, "reason": None, "streams": details, "blocking": []}


async def _load_equity_snapshots(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[FuturesAccountSnapshot]:
    result = await session.execute(
        select(FuturesAccountSnapshot)
        .where(
            FuturesAccountSnapshot.user_id == user_id,
            FuturesAccountSnapshot.exchange == exchange,
            FuturesAccountSnapshot.equity.is_not(None),
        )
        .order_by(
            FuturesAccountSnapshot.source_ts.asc(),
            FuturesAccountSnapshot.id.asc(),
        )
    )
    return list(result.scalars().all())


async def _load_external_flows(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    opening_ts: datetime,
    ending_ts: datetime,
) -> Sequence[CapitalFlowLedger]:
    result = await session.execute(
        select(CapitalFlowLedger)
        .where(
            CapitalFlowLedger.user_id == user_id,
            CapitalFlowLedger.exchange == exchange,
            CapitalFlowLedger.entry_type.in_(EXTERNAL_ENTRY_TYPES),
            CapitalFlowLedger.occurred_at.is_not(None),
            CapitalFlowLedger.occurred_at > opening_ts,
            CapitalFlowLedger.occurred_at <= ending_ts,
        )
        .order_by(CapitalFlowLedger.occurred_at.asc())
    )
    return list(result.scalars().all())


def _unavailable(
    reason: str,
    *,
    coverage_detail: Optional[Dict[str, Any]] = None,
    opening_equity: Optional[float] = None,
    ending_equity: Optional[float] = None,
    opening_source_ts: Optional[datetime] = None,
    ending_source_ts: Optional[datetime] = None,
) -> Dict[str, Any]:
    return {
        "account_return_pct": None,
        "account_return_pct_reason": reason,
        "net_account_profit_usd": None,
        "net_account_profit_usd_reason": reason,
        "opening_equity": opening_equity,
        "ending_equity": ending_equity,
        "net_external_flows": None,
        "opening_source_ts": opening_source_ts,
        "ending_source_ts": ending_source_ts,
        "external_flow_count": 0,
        "basis": None,
        "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
        "complete": False,
        "reason": reason,
        "coverage": coverage_detail,
    }
