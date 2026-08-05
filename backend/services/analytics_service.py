"""Portfolio analytics service — performance metrics, equity curve, daily PnL, allocation.

All functions are async and accept an ``AsyncSession`` so they can be called
directly from route handlers. They read from the already-cached
``PositionHistory``, ``PortfolioSnapshot`` and ``PortfolioBalance`` tables
(no outbound exchange API calls).
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    CapitalFlowLedger,
    FuturesAccountSnapshot,
    PortfolioBalance,
    PositionHistory,
    TradeJournalEntry,
)
from backend.services.phase3_account_return import EXTERNAL_ENTRY_TYPES, compute_account_return

logger = logging.getLogger(__name__)


# ── Performance metrics ─────────────────────────────────────────────────────


async def compute_performance_metrics(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Dict[str, Any]:
    """Compute trading performance metrics from closed positions.

    Closed-position realised PnL is always reconstructed from PositionHistory.
    Phase 3 adds cash-flow-adjusted account return when futures equity snapshots
    and complete external capital-flow coverage exist.
    """
    result = await session.execute(
        select(PositionHistory)
        .where(
            PositionHistory.user_id == user_id,
            PositionHistory.exchange == exchange,
        )
        .order_by(PositionHistory.close_time.asc().nullslast())
    )
    positions: List[PositionHistory] = list(result.scalars().all())

    total_trades = len(positions)
    account = await compute_account_return(session, user_id, exchange)

    if total_trades == 0:
        metrics = _empty_metrics()
        metrics = await _merge_account_equity_drawdown(session, user_id, exchange, metrics)
        return _merge_account_return(metrics, account)

    pnls = [float(p.pnl or 0.0) for p in positions]

    winning = [p for p in pnls if p > 0]
    losing = [p for p in pnls if p < 0]
    winning_trades = len(winning)
    losing_trades = len(losing)

    win_rate = (winning_trades / total_trades) * 100 if total_trades else 0.0

    gross_profit = sum(winning)
    gross_loss = abs(sum(losing))
    profit_factor: Optional[float]
    if gross_loss == 0:
        profit_factor = None
    else:
        profit_factor = gross_profit / gross_loss

    average_win = statistics.mean(winning) if winning else 0.0
    average_loss = statistics.mean(losing) if losing else 0.0

    best_trade = max(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0
    total_pnl = sum(pnls)

    trade_quality_score: Optional[float] = None
    if len(pnls) >= 2:
        std_pnl = statistics.stdev(pnls)
        if std_pnl != 0:
            mean_pnl = statistics.mean(pnls)
            trade_quality_score = (mean_pnl / std_pnl) * math.sqrt(len(pnls))

    realised_pnl_drawdown_usd, realised_pnl_drawdown_pct = _compute_max_drawdown(pnls)
    rounded_trade_quality = round(trade_quality_score, 4) if trade_quality_score is not None else None
    rounded_drawdown_usd = round(realised_pnl_drawdown_usd, 2)
    rounded_drawdown_pct = round(realised_pnl_drawdown_pct, 2) if realised_pnl_drawdown_pct is not None else None

    metrics = {
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "trade_quality_score": rounded_trade_quality,
        "trade_quality_basis": "per_trade_pnl_dispersion",
        "realised_pnl_drawdown_usd": rounded_drawdown_usd,
        "realised_pnl_drawdown_pct": rounded_drawdown_pct,
        "drawdown_basis": "cumulative_closed_pnl",
        "account_equity_drawdown_usd": None,
        "account_equity_drawdown_pct": None,
        "account_equity_drawdown_reason": "no_account_equity_data",
        # Backward-compatible aliases retained for Phase 0 clients. New UI uses
        # the explicit replacement names above.
        "sharpe_ratio": rounded_trade_quality,
        "max_drawdown": rounded_drawdown_usd,
        "max_drawdown_percent": rounded_drawdown_pct,
        "average_win": round(average_win, 2),
        "average_loss": round(average_loss, 2),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "best_trade": round(best_trade, 2),
        "worst_trade": round(worst_trade, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_basis": "MEXC-reported closed-position PnL",
        # Never sum per-position ROI into an account return %.
        "total_pnl_percent": None,
        "total_pnl_percent_reason": "not_a_valid_account_return",
        "source": "PositionHistory.pnl",
        "basis": "closed_position_reconstruction",
    }
    metrics = await _merge_account_equity_drawdown(session, user_id, exchange, metrics)
    return _merge_account_return(metrics, account)


def _empty_metrics() -> Dict[str, Any]:
    """Return closed-trade metrics zeros; account-return fields filled by merger."""
    return {
        "win_rate": 0.0,
        "profit_factor": None,
        "trade_quality_score": None,
        "trade_quality_basis": "per_trade_pnl_dispersion",
        "realised_pnl_drawdown_usd": 0.0,
        "realised_pnl_drawdown_pct": 0.0,
        "drawdown_basis": "cumulative_closed_pnl",
        "account_equity_drawdown_usd": None,
        "account_equity_drawdown_pct": None,
        "account_equity_drawdown_reason": "no_account_equity_data",
        "sharpe_ratio": None,
        "max_drawdown": 0.0,
        "max_drawdown_percent": 0.0,
        "average_win": 0.0,
        "average_loss": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "best_trade": 0.0,
        "worst_trade": 0.0,
        "total_pnl": 0.0,
        "total_pnl_basis": "MEXC-reported closed-position PnL",
        "total_pnl_percent": None,
        "total_pnl_percent_reason": "not_a_valid_account_return",
        "source": "PositionHistory.pnl",
        "basis": "closed_position_reconstruction",
    }


async def _merge_account_equity_drawdown(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    equity_dd = await _account_equity_drawdown(session, user_id, exchange)
    metrics["account_equity_drawdown_usd"] = equity_dd["usd"]
    metrics["account_equity_drawdown_pct"] = equity_dd["pct"]
    metrics["account_equity_drawdown_reason"] = equity_dd["reason"]
    return metrics


def _merge_account_return(metrics: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay Phase 3 account-return fields onto closed-position metrics."""
    reason = account.get("account_return_pct_reason") or account.get("reason")
    available = account.get("account_return_pct") is not None
    metrics["account_return_pct"] = account.get("account_return_pct")
    metrics["account_return_pct_reason"] = None if available else reason
    metrics["net_account_profit_usd"] = account.get("net_account_profit_usd")
    metrics["net_account_profit_usd_reason"] = (
        None if account.get("net_account_profit_usd") is not None else reason
    )
    metrics["opening_equity"] = account.get("opening_equity")
    metrics["ending_equity"] = account.get("ending_equity")
    metrics["net_external_flows"] = account.get("net_external_flows")
    metrics["account_return_basis"] = account.get("basis")
    metrics["complete"] = bool(available)
    metrics["unavailable_reason"] = None if available else reason
    # total_pnl_percent remains null; expose reason aligned with account return gate
    if not available:
        metrics["total_pnl_percent_reason"] = reason or "capital_history_missing"
    return metrics


def _compute_max_drawdown(pnls: List[float]) -> tuple[float, Optional[float]]:
    """Compute drawdown of cumulative realised closed-position PnL."""
    if not pnls:
        return 0.0, 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    max_dd_pct: Optional[float] = 0.0

    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown
            max_dd_pct = (drawdown / peak) * 100 if peak > 0 else None

    return max_dd, max_dd_pct


def _compute_series_drawdown(values: List[float]) -> tuple[Optional[float], Optional[float]]:
    """Peak-to-trough drawdown over an equity level series (not cumulative PnL)."""
    if len(values) < 2:
        return None, None
    peak = values[0]
    max_dd = 0.0
    max_dd_pct: Optional[float] = 0.0
    for value in values:
        if value > peak:
            peak = value
        drawdown = peak - value
        if drawdown > max_dd:
            max_dd = drawdown
            max_dd_pct = (drawdown / peak) * 100 if abs(peak) > 1e-8 else None
    return max_dd, max_dd_pct


async def _load_futures_equity_series(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> tuple[List[FuturesAccountSnapshot], Optional[str]]:
    """Load settlement-aware futures equity history (USDT preferred over dust)."""
    from backend.services.futures_settlement import choose_settlement_asset_for_series

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
    rows = list(result.scalars().all())
    if not rows:
        return [], None
    peak: Dict[str, float] = {}
    for row in rows:
        asset = (row.settlement_asset or "USDT").upper()
        peak[asset] = max(peak.get(asset, 0.0), abs(float(row.equity or 0.0)))
    chosen = choose_settlement_asset_for_series(peak.keys(), peak)
    if chosen is None:
        return rows, None
    series = [r for r in rows if (r.settlement_asset or "").upper() == chosen]
    return series, chosen


async def _account_equity_drawdown(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Dict[str, Any]:
    series, settlement = await _load_futures_equity_series(session, user_id, exchange)
    if len(series) < 2:
        return {
            "usd": None,
            "pct": None,
            "reason": "no_account_equity_data" if not series else "insufficient_equity_snapshots",
            "settlement_asset": settlement,
        }
    values = [float(s.equity or 0.0) for s in series]
    if all(abs(v) <= 1e-8 for v in values):
        return {
            "usd": 0.0,
            "pct": None,
            "reason": "futures_equity_flat",
            "settlement_asset": settlement,
        }
    usd, pct = _compute_series_drawdown(values)
    return {
        "usd": round(usd, 2) if usd is not None else None,
        "pct": round(pct, 2) if pct is not None else None,
        "reason": None,
        "settlement_asset": settlement,
    }


# ── Equity curve ────────────────────────────────────────────────────────────


async def get_equity_curve(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Dict[str, Any]:
    """Return futures wallet equity curve + external capital-flow markers.

    Source of truth is ``FuturesAccountSnapshot.equity`` for the preferred
    settlement series (USDT over dust). Spot / ``PortfolioSnapshot`` is never
    used as account equity. External capital events (deposit, withdrawal,
    futures_transfer) are returned as markers for the chart.
    """
    series, settlement = await _load_futures_equity_series(session, user_id, exchange)
    points: List[Dict[str, Any]] = []
    for snap in series:
        if snap.equity is None or snap.source_ts is None:
            continue
        points.append(
            {
                "timestamp": _iso_ts(snap.source_ts),
                "total_value": round(float(snap.equity), 4),
                "basis": "futures_equity",
                "settlement_asset": snap.settlement_asset,
            }
        )

    markers = await _capital_flow_markers(session, user_id, exchange)

    if not points:
        return {
            "points": [],
            "markers": markers,
            "basis": None,
            "source": "FuturesAccountSnapshot.equity",
            "settlement_asset": settlement,
            "complete": False,
            "unavailable_reason": "no_account_equity_data",
        }

    return {
        "points": points,
        "markers": markers,
        "basis": "futures_equity",
        "source": "FuturesAccountSnapshot.equity",
        "settlement_asset": settlement,
        "complete": True,
        "unavailable_reason": None,
    }


async def _capital_flow_markers(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[Dict[str, Any]]:
    result = await session.execute(
        select(CapitalFlowLedger)
        .where(
            CapitalFlowLedger.user_id == user_id,
            CapitalFlowLedger.exchange == exchange,
            CapitalFlowLedger.entry_type.in_(EXTERNAL_ENTRY_TYPES),
            CapitalFlowLedger.occurred_at.is_not(None),
        )
        .order_by(CapitalFlowLedger.occurred_at.asc())
    )
    markers: List[Dict[str, Any]] = []
    for row in result.scalars().all():
        markers.append(
            {
                "timestamp": _iso_ts(row.occurred_at),
                "entry_type": row.entry_type,
                "signed_amount": round(float(row.signed_amount), 4)
                if row.signed_amount is not None
                else None,
                "asset": row.asset,
                "exchange_entry_id": row.exchange_entry_id,
            }
        )
    return markers


# ── Daily / period PnL ──────────────────────────────────────────────────────


async def get_daily_pnl(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    timezone_name: str = "UTC",
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate PositionHistory PnL by local close-time date."""
    tz = _load_timezone(timezone_name)
    result = await session.execute(
        select(PositionHistory)
        .where(
            PositionHistory.user_id == user_id,
            PositionHistory.exchange == exchange,
        )
        .order_by(PositionHistory.close_time.asc().nullslast())
    )
    positions: List[PositionHistory] = list(result.scalars().all())

    daily: Dict[str, float] = {}
    for position in positions:
        if position.close_time is None:
            continue
        close_utc = _as_utc(position.close_time)
        if from_ts is not None and close_utc < _as_utc(from_ts):
            continue
        if to_ts is not None and close_utc > _as_utc(to_ts):
            continue
        date_str = close_utc.astimezone(tz).strftime("%Y-%m-%d")
        daily[date_str] = daily.get(date_str, 0.0) + float(position.pnl or 0.0)

    return {
        "exchange": exchange,
        "timezone": timezone_name,
        "period": {
            "from": _iso_ts(from_ts) if from_ts else None,
            "to": _iso_ts(to_ts) if to_ts else None,
        },
        "source": "PositionHistory.close_time",
        "basis": "MEXC-reported closed-position PnL grouped by local date",
        "complete": False,
        "unavailable_reason": None,
        "days": [
            {"date": date, "pnl": round(pnl, 2)}
            for date, pnl in sorted(daily.items())
        ],
    }


async def get_period_pnl(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    timezone_name: str = "UTC",
    group_by: str = "week",
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate PositionHistory PnL by day/week/month in a local timezone."""
    tz = _load_timezone(timezone_name)
    result = await session.execute(
        select(PositionHistory)
        .where(PositionHistory.user_id == user_id, PositionHistory.exchange == exchange)
        .order_by(PositionHistory.close_time.asc().nullslast())
    )
    positions: List[PositionHistory] = list(result.scalars().all())

    buckets: Dict[str, float] = {}
    for position in positions:
        if position.close_time is None:
            continue
        close_utc = _as_utc(position.close_time)
        if from_ts is not None and close_utc < _as_utc(from_ts):
            continue
        if to_ts is not None and close_utc > _as_utc(to_ts):
            continue
        local = close_utc.astimezone(tz)
        if group_by == "day":
            key = local.strftime("%Y-%m-%d")
        elif group_by == "month":
            key = local.strftime("%Y-%m")
        elif group_by == "week":
            iso = local.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        else:
            raise ValueError(f"Unsupported group_by: {group_by}")
        buckets[key] = buckets.get(key, 0.0) + float(position.pnl or 0.0)

    return {
        "exchange": exchange,
        "timezone": timezone_name,
        "group_by": group_by,
        "periods": [
            {"period": period, "pnl": round(pnl, 2)}
            for period, pnl in sorted(buckets.items())
        ],
    }


# ── Allocation ─────────────────────────────────────────────────────────────


async def get_allocation(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    account_type: str = "spot",
) -> Dict[str, Any]:
    """Compute current asset allocation from PortfolioBalance rows.

    Phase 0 labels the existing balance allocation as spot only. Futures
    collateral allocation is unavailable until futures account snapshots exist.
    """
    account_type = account_type.strip().lower()
    if account_type != "spot":
        return {
            "account_type": account_type,
            "items": [],
            "source": None,
            "basis": None,
            "complete": False,
            "unavailable_reason": "futures_equity_not_available",
        }

    result = await session.execute(
        select(PortfolioBalance)
        .where(
            PortfolioBalance.user_id == user_id,
            PortfolioBalance.exchange == exchange,
        )
    )
    balances: List[PortfolioBalance] = list(result.scalars().all())

    base_response = {
        "account_type": "spot",
        "source": "PortfolioBalance",
        "basis": "spot_balances_usd",
    }

    if not balances:
        return {**base_response, "items": [], "complete": True, "unavailable_reason": None}

    has_usd = any(b.usd_value is not None and b.usd_value > 0 for b in balances)
    if not has_usd:
        return {
            **base_response,
            "items": [],
            "complete": False,
            "unavailable_reason": "spot_usd_values_missing",
        }

    items: List[Dict[str, Any]] = []
    total_usd = 0.0
    for balance in balances:
        val = balance.usd_value
        if val is None or val <= 0:
            continue
        items.append({"asset": balance.asset, "usd_value": round(float(val), 2), "account_type": "spot"})
        total_usd += float(val)

    for item in items:
        item["percentage"] = round((item["usd_value"] / total_usd) * 100, 2) if total_usd > 0 else 0.0

    items.sort(key=lambda item: item["usd_value"], reverse=True)
    return {**base_response, "items": items, "complete": True, "unavailable_reason": None}


# ── Phase 1 closed-position analytics calculator ────────────────────────────

PNL_SOURCE = "PositionHistory.pnl"
PNL_BASIS = "MEXC-reported closed-position PnL"
CURRENCY_UNIT = "USDT"
FEE_STATUS = "fee_net_pnl_unavailable_phase2_ledger_required"
HISTORY_REASON = "full_history_sync_not_implemented_phase2"


async def compute_closed_position_analytics(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    filters: Optional[Dict[str, Any]] = None,
    pagination: Optional[Dict[str, int]] = None,
    sort: str = "-close_time",
    timezone_name: str = "UTC",
    period: str = "week",
) -> Dict[str, Any]:
    """Compute Phase 1 closed-position analytics from cached PositionHistory rows.

    The caller supplies the already-authenticated ``user_id`` and exchange slug.
    This function performs no exchange/network calls and applies one shared filter
    pass before deriving overview, periods, breakdowns, calendar and explorer data.
    """
    tz = _load_timezone(timezone_name)
    filters = dict(filters or {})
    pagination = dict(pagination or {})
    limit = int(pagination.get("limit", 50))
    offset = int(pagination.get("offset", 0))
    if limit > 200:
        raise ValueError("limit must be <= 200")
    if limit < 0 or offset < 0:
        raise ValueError("limit and offset must be non-negative")
    if period not in {"day", "week", "month"}:
        raise ValueError(f"Unsupported period: {period}")

    result = await session.execute(
        select(PositionHistory)
        .where(PositionHistory.user_id == user_id, PositionHistory.exchange == exchange)
        .order_by(PositionHistory.close_time.asc().nullslast(), PositionHistory.id.asc())
    )
    stored_positions: List[PositionHistory] = list(result.scalars().all())
    filtered_positions, excluded_reasons = _filter_closed_positions(stored_positions, filters)
    filters_applied = _filters_applied(filters, timezone_name, period)

    overview = _closed_position_overview(filtered_positions, filters, tz)
    periods = _closed_position_periods(filtered_positions, filters_applied, tz, period)
    calendar_days = _closed_position_calendar_days(filtered_positions, tz)
    breakdowns = {
        "symbol": _closed_position_breakdown(filtered_positions, "symbol"),
        "side": _closed_position_breakdown(filtered_positions, "side"),
        "duration": _closed_position_breakdown(filtered_positions, "duration"),
        "leverage": _closed_position_breakdown(filtered_positions, "leverage"),
        "pair_direction": _closed_position_breakdown(filtered_positions, "pair_direction"),
    }
    explorer = _closed_position_explorer(filtered_positions, filters_applied, sort, limit, offset)

    history = _closed_position_history(filtered_positions)
    basis = _closed_position_basis()
    return {
        "exchange": exchange,
        "filters_applied": filters_applied,
        "basis": basis,
        "history": history,
        "excluded_reasons": excluded_reasons,
        "overview": overview,
        "periods": {
            "exchange": exchange,
            "filters_applied": filters_applied,
            "basis": basis,
            "history": history,
            "excluded_reasons": excluded_reasons,
            "period": period,
            "items": periods,
            "totals": {
                "trade_count": sum(item["trade_count"] for item in periods),
                "total_pnl": _money(sum((_dec(item["total_pnl"]) for item in periods), Decimal("0"))),
            },
        },
        "calendar_days": calendar_days,
        "concentration": _closed_position_concentration(filtered_positions),
        "breakdowns": breakdowns,
        "explorer": {
            "exchange": exchange,
            "filters_applied": filters_applied,
            "sort": sort,
            "limit": limit,
            "offset": offset,
            "total": len(filtered_positions),
            "has_more": offset + limit < len(filtered_positions),
            "basis": basis,
            "history": history,
            "excluded_reasons": excluded_reasons,
            "items": explorer,
        },
        "unavailable": {
            "fee_net_pnl": {"value": None, "reason": FEE_STATUS},
            "account_return_pct": {"value": None, "reason": "capital_history_missing"},
            "account_equity": {"value": None, "reason": "account_equity_unavailable_phase3"},
        },
    }


def _filter_closed_positions(
    positions: Iterable[PositionHistory], filters: Dict[str, Any]
) -> tuple[List[PositionHistory], Dict[str, int]]:
    symbols = {str(symbol).upper() for symbol in _csv(filters.get("symbols"))}
    side = _normalise_side(filters.get("side")) if filters.get("side") is not None else None
    close_reasons = {str(reason).lower() for reason in _csv(filters.get("close_reason"))}
    from_ts = _as_utc(filters["from"]) if filters.get("from") is not None else None
    to_ts = _as_utc(filters["to"]) if filters.get("to") is not None else None
    leverage_min = _optional_dec(filters.get("leverage_min"))
    leverage_max = _optional_dec(filters.get("leverage_max"))
    duration_min = _optional_dec(filters.get("duration_min_minutes"))
    duration_max = _optional_dec(filters.get("duration_max_minutes"))
    pnl_min = _optional_dec(filters.get("pnl_min"))
    pnl_max = _optional_dec(filters.get("pnl_max"))
    excluded: Dict[str, int] = {}
    output: List[PositionHistory] = []

    for position in positions:
        close_utc = _as_utc(position.close_time) if position.close_time is not None else None
        if close_utc is not None and from_ts is not None and close_utc < from_ts:
            continue
        if close_utc is not None and to_ts is not None and close_utc >= to_ts:
            continue
        if symbols and str(position.symbol).upper() not in symbols:
            continue
        if side and _normalise_side(position.side) != side:
            continue
        if close_reasons and str(position.close_reason or "").lower() not in close_reasons:
            continue
        pnl = _position_pnl(position)
        if pnl_min is not None and pnl < pnl_min:
            continue
        if pnl_max is not None and pnl > pnl_max:
            continue
        leverage = _position_leverage(position)
        duration = _duration_minutes(position)
        if leverage_min is not None or leverage_max is not None:
            if leverage is None:
                excluded["missing_leverage"] = excluded.get("missing_leverage", 0) + 1
                if (duration_min is not None or duration_max is not None) and duration is None:
                    excluded["missing_duration"] = excluded.get("missing_duration", 0) + 1
                continue
            if leverage_min is not None and leverage < leverage_min:
                continue
            if leverage_max is not None and leverage > leverage_max:
                continue
        if duration_min is not None or duration_max is not None:
            if duration is None:
                excluded["missing_duration"] = excluded.get("missing_duration", 0) + 1
                continue
            if duration_min is not None and Decimal(str(duration)) < duration_min:
                continue
            if duration_max is not None and Decimal(str(duration)) > duration_max:
                continue
        output.append(position)
    return output, excluded


def _closed_position_overview(positions: List[PositionHistory], filters: Dict[str, Any], tz: ZoneInfo) -> Dict[str, Any]:
    pnls = [_position_pnl(position) for position in positions]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    breakevens = [pnl for pnl in pnls if pnl == 0]
    total_trades = len(pnls)
    total_pnl = sum(pnls, Decimal("0"))
    gross_profit = sum(wins, Decimal("0"))
    gross_loss_abs = abs(sum(losses, Decimal("0")))
    active_days = len({ _as_utc(p.close_time).astimezone(tz).date() for p in positions if p.close_time is not None })
    calendar_days = _calendar_day_count(positions, filters, tz)

    overview: Dict[str, Any] = {
        "total_trades": total_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "breakeven_trades": len(breakevens),
        "total_pnl": _money(total_pnl),
        "gross_profit": _money(gross_profit),
        "gross_loss_abs": _money(gross_loss_abs),
        "average_win": _money(sum(wins, Decimal("0")) / Decimal(len(wins))) if wins else None,
        "average_win_reason": None if wins else "no_winning_trades",
        "average_loss": _money(sum(losses, Decimal("0")) / Decimal(len(losses))) if losses else None,
        "average_loss_reason": None if losses else "no_losing_trades",
        "average_trade_pnl": _money(total_pnl / Decimal(total_trades)) if total_trades else None,
        "average_trade_pnl_reason": None if total_trades else "insufficient_data",
        "expectancy_per_trade": _money(total_pnl / Decimal(total_trades)) if total_trades else None,
        "expectancy_per_trade_reason": None if total_trades else "insufficient_data",
        "best_trade": _money(max(pnls)) if pnls else None,
        "best_trade_reason": None if pnls else "insufficient_data",
        "worst_trade": _money(min(pnls)) if pnls else None,
        "worst_trade_reason": None if pnls else "insufficient_data",
        "active_days": active_days,
        "calendar_days": calendar_days,
        "average_pnl_per_active_day": _money(total_pnl / Decimal(active_days)) if active_days else None,
        "average_pnl_per_active_day_label": "per active trading day",
        "average_pnl_per_active_day_reason": None if active_days else "no_active_days",
        "average_pnl_per_calendar_day": _money(total_pnl / Decimal(calendar_days)) if calendar_days else None,
        "average_pnl_per_calendar_day_label": "per calendar day",
        "average_pnl_per_calendar_day_reason": None if calendar_days else "no_calendar_range",
    }
    for name, count in [("win_rate_pct", len(wins)), ("loss_rate_pct", len(losses)), ("breakeven_rate_pct", len(breakevens))]:
        overview[name] = _ratio_pct(Decimal(count), Decimal(total_trades)) if total_trades else None
        overview[f"{name}_reason"] = None if total_trades else "insufficient_data"
    overview["profit_factor"] = _ratio(gross_profit, gross_loss_abs) if gross_loss_abs != 0 else None
    overview["profit_factor_reason"] = None if gross_loss_abs != 0 else "no_losing_trades"
    if wins and losses:
        overview["payoff_ratio"] = _ratio(sum(wins, Decimal("0")) / Decimal(len(wins)), abs(sum(losses, Decimal("0")) / Decimal(len(losses))))
        overview["payoff_ratio_reason"] = None
    else:
        overview["payoff_ratio"] = None
        overview["payoff_ratio_reason"] = "no_winning_trades" if not wins else "no_losing_trades"
    overview.update(_streaks(positions))
    return overview


def _closed_position_periods(
    positions: List[PositionHistory], filters_applied: Dict[str, Any], tz: ZoneInfo, period: str
) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for position in positions:
        if position.close_time is None:
            continue
        local = _as_utc(position.close_time).astimezone(tz)
        label, start_local, end_local = _period_label_and_bounds(local, period)
        bucket = buckets.setdefault(label, {"label": label, "period_start": start_local.astimezone(timezone.utc).isoformat(), "period_end": end_local.astimezone(timezone.utc).isoformat(), "trade_count": 0, "total_pnl_dec": Decimal("0"), "basis": PNL_BASIS, "currency_unit": CURRENCY_UNIT})
        bucket["trade_count"] += 1
        bucket["total_pnl_dec"] += _position_pnl(position)
    items = []
    for bucket in sorted(buckets.values(), key=lambda item: item["period_start"]):
        total = bucket.pop("total_pnl_dec")
        bucket["total_pnl"] = _money(total)
        items.append(bucket)
    return items


def _closed_position_calendar_days(positions: List[PositionHistory], tz: ZoneInfo) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for position in positions:
        if position.close_time is None:
            continue
        label = _as_utc(position.close_time).astimezone(tz).strftime("%Y-%m-%d")
        bucket = buckets.setdefault(label, {"date": label, "trade_count": 0, "total_pnl_dec": Decimal("0"), "currency_unit": CURRENCY_UNIT, "basis": PNL_BASIS})
        bucket["trade_count"] += 1
        bucket["total_pnl_dec"] += _position_pnl(position)
    items = []
    for bucket in sorted(buckets.values(), key=lambda item: item["date"]):
        total = bucket.pop("total_pnl_dec")
        bucket["total_pnl"] = _money(total)
        items.append(bucket)
    return items


def _closed_position_breakdown(positions: List[PositionHistory], group_by: str) -> List[Dict[str, Any]]:
    groups: Dict[str, List[PositionHistory]] = defaultdict(list)
    for position in positions:
        groups[_breakdown_key(position, group_by)].append(position)
    return [_breakdown_row(key, rows) for key, rows in sorted(groups.items(), key=lambda item: item[0])]


def _breakdown_row(key: str, positions: List[PositionHistory]) -> Dict[str, Any]:
    pnls = [_position_pnl(position) for position in positions]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    total = sum(pnls, Decimal("0"))
    return {
        "key": key,
        "trade_count": len(positions),
        "total_pnl": _money(total),
        "gross_profit": _money(sum(wins, Decimal("0"))),
        "gross_loss_abs": _money(abs(sum(losses, Decimal("0")))),
        "win_rate_pct": _ratio_pct(Decimal(len(wins)), Decimal(len(positions))) if positions else None,
        "average_pnl": _money(total / Decimal(len(positions))) if positions else None,
        "best_trade": _money(max(pnls)) if pnls else None,
        "worst_trade": _money(min(pnls)) if pnls else None,
        "basis": PNL_BASIS,
        "currency_unit": CURRENCY_UNIT,
    }


def _closed_position_concentration(positions: List[PositionHistory], top_n: int = 1) -> Dict[str, Any]:
    by_symbol = _closed_position_breakdown(positions, "symbol")
    profits = sorted([_dec(row["gross_profit"]) for row in by_symbol if _dec(row["gross_profit"]) > 0], reverse=True)
    losses = sorted([_dec(row["gross_loss_abs"]) for row in by_symbol if _dec(row["gross_loss_abs"]) > 0], reverse=True)
    total_profit = sum(profits, Decimal("0"))
    total_loss = sum(losses, Decimal("0"))
    return {
        "gross_profit_top_1_contribution_pct": _top_contribution(profits, total_profit, top_n),
        "gross_profit_top_1_contribution_pct_reason": None if total_profit else "zero_gross_profit",
        "gross_profit_hhi": _hhi(profits, total_profit),
        "gross_profit_hhi_reason": None if total_profit else "zero_gross_profit",
        "gross_loss_top_1_contribution_pct": _top_contribution(losses, total_loss, top_n),
        "gross_loss_top_1_contribution_pct_reason": None if total_loss else "zero_gross_loss",
        "gross_loss_hhi": _hhi(losses, total_loss),
        "gross_loss_hhi_reason": None if total_loss else "zero_gross_loss",
    }


def _closed_position_explorer(
    positions: List[PositionHistory], filters_applied: Dict[str, Any], sort: str, limit: int, offset: int
) -> List[Dict[str, Any]]:
    ordered = _sort_positions(positions, sort)
    return [_explorer_item(position) for position in ordered[offset : offset + limit]]


def _explorer_item(position: PositionHistory) -> Dict[str, Any]:
    duration_minutes = _duration_minutes(position)
    leverage = _position_leverage(position)
    unavailable_reasons: Dict[str, Any] = {"fee_net_pnl": FEE_STATUS}
    if duration_minutes is None:
        unavailable_reasons["missing_duration"] = True
    if leverage is None:
        unavailable_reasons["missing_leverage"] = True

    return {
        "id": position.id,
        "symbol": position.symbol,
        "side": _normalise_side(position.side),
        "size": position.size,
        "size_unit": "contracts",
        "contract_size": position.contract_size,
        "entry_price": position.entry_price,
        "exit_price": position.exit_price,
        "pnl": _money(_position_pnl(position)),
        "pnl_basis": PNL_BASIS,
        "currency_unit": CURRENCY_UNIT,
        "fee_status": FEE_STATUS,
        "pnl_percent": position.pnl_percent,
        "leverage": float(leverage) if leverage is not None else None,
        "open_time": _iso_ts(position.open_time) if position.open_time else None,
        "close_time": _iso_ts(position.close_time) if position.close_time else None,
        "duration_minutes": duration_minutes,
        "close_reason": position.close_reason,
        "unavailable_reasons": unavailable_reasons,
    }


def _closed_position_history(positions: List[PositionHistory]) -> Dict[str, Any]:
    close_times = [_as_utc(position.close_time) for position in positions if position.close_time is not None]
    return {
        "history_scope": "stored_closed_positions",
        "history_completeness": "unknown",
        "reason": HISTORY_REASON,
        "row_count": len(positions),
        "first_close_time": min(close_times).isoformat() if close_times else None,
        "last_close_time": max(close_times).isoformat() if close_times else None,
    }


def _closed_position_basis() -> Dict[str, str]:
    return {"pnl_source": PNL_SOURCE, "pnl_basis": PNL_BASIS, "currency_unit": CURRENCY_UNIT, "fee_status": FEE_STATUS, "size_unit": "contracts"}


def _filters_applied(filters: Dict[str, Any], timezone_name: str, period: str) -> Dict[str, Any]:
    rendered = {"timezone": timezone_name, "period": period}
    for key, value in sorted(filters.items()):
        if isinstance(value, datetime):
            rendered[key] = _iso_ts(value)
        elif isinstance(value, list):
            rendered[key] = [str(v).upper() if key == "symbols" else v for v in value]
        else:
            rendered[key] = str(value).upper() if key == "symbols" else value
    if "symbols" in rendered and isinstance(rendered["symbols"], str):
        rendered["symbols"] = [symbol.upper() for symbol in _csv(rendered["symbols"])]
    return rendered


def _period_label_and_bounds(local: datetime, period: str) -> tuple[str, datetime, datetime]:
    if period == "day":
        start = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
        return local.strftime("%Y-%m-%d"), start, start + timedelta(days=1)
    if period == "week":
        start_date = local.date() - timedelta(days=local.weekday())
        start = datetime.combine(start_date, time.min, tzinfo=local.tzinfo)
        iso = local.isocalendar()
        return f"{iso.year}-W{iso.week:02d}", start, start + timedelta(days=7)
    start = datetime(local.year, local.month, 1, tzinfo=local.tzinfo)
    end = datetime(local.year + (1 if local.month == 12 else 0), 1 if local.month == 12 else local.month + 1, 1, tzinfo=local.tzinfo)
    return local.strftime("%Y-%m"), start, end


def _calendar_day_count(positions: List[PositionHistory], filters: Dict[str, Any], tz: ZoneInfo) -> int:
    close_dates = sorted({_as_utc(p.close_time).astimezone(tz).date() for p in positions if p.close_time is not None})
    if not close_dates:
        return 0
    from_ts = _as_utc(filters["from"]).astimezone(tz) if filters.get("from") is not None else None
    to_ts = _as_utc(filters["to"]).astimezone(tz) if filters.get("to") is not None else None
    start = from_ts.date() if from_ts else close_dates[0]
    if to_ts:
        end = (to_ts - timedelta(microseconds=1)).date()
    else:
        end = close_dates[-1]
    if end < start:
        return 0
    return (end - start).days + 1


def _streaks(positions: List[PositionHistory]) -> Dict[str, Any]:
    ordered = sorted(positions, key=lambda p: (_as_utc(p.close_time) if p.close_time else datetime.max.replace(tzinfo=timezone.utc), p.id or 0))
    if not ordered:
        return {"max_win_streak": 0, "max_loss_streak": 0, "current_streak": None, "current_streak_reason": "insufficient_data"}
    max_win = max_loss = current_len = 0
    current_type: Optional[str] = None
    for position in ordered:
        pnl = _position_pnl(position)
        kind = "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven"
        current_len = current_len + 1 if kind == current_type else 1
        current_type = kind
        if kind == "win":
            max_win = max(max_win, current_len)
        elif kind == "loss":
            max_loss = max(max_loss, current_len)
    return {"max_win_streak": max_win, "max_loss_streak": max_loss, "current_streak": {"type": current_type, "length": current_len}, "current_streak_reason": None}


def _sort_positions(positions: List[PositionHistory], sort: str) -> List[PositionHistory]:
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    if field not in {"close_time", "pnl", "symbol", "side", "leverage", "duration_minutes"}:
        raise ValueError(f"Unsupported sort: {sort}")
    def key(position: PositionHistory):
        if field == "close_time":
            primary = _as_utc(position.close_time) if position.close_time else datetime.max.replace(tzinfo=timezone.utc)
        elif field == "pnl":
            primary = float(_position_pnl(position))
        elif field == "duration_minutes":
            primary = _duration_minutes(position)
        else:
            primary = getattr(position, field)
        return (primary is None, primary)
    by_id = sorted(positions, key=lambda position: position.id or 0)
    return sorted(by_id, key=key, reverse=descending)


def _breakdown_key(position: PositionHistory, group_by: str) -> str:
    if group_by == "symbol":
        return str(position.symbol).upper()
    if group_by == "side":
        return _normalise_side(position.side)
    if group_by == "pair_direction":
        return f"{str(position.symbol).upper()}:{_normalise_side(position.side)}"
    if group_by == "duration":
        minutes = _duration_minutes(position)
        if minutes is None:
            return "unknown_duration"
        if minutes < 1440:
            return "<1d"
        if minutes <= 10080:
            return "1-7d"
        return ">7d"
    if group_by == "leverage":
        leverage = _position_leverage(position)
        if leverage is None:
            return "unknown_leverage"
        if leverage <= 5:
            return "<=5x"
        if leverage <= 10:
            return ">5x-10x"
        return ">10x"
    raise ValueError(f"Unsupported group_by: {group_by}")


def _duration_minutes(position: PositionHistory) -> Optional[int]:
    if position.open_time is None or position.close_time is None:
        return None
    return int((_as_utc(position.close_time) - _as_utc(position.open_time)).total_seconds() // 60)


def _position_pnl(position: PositionHistory) -> Decimal:
    return Decimal(str(position.pnl or 0))


def _position_leverage(position: PositionHistory) -> Optional[Decimal]:
    if position.leverage is None or position.leverage <= 0:
        return None
    return Decimal(str(position.leverage))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ratio(value: Decimal, denominator: Decimal) -> float:
    return float((value / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _ratio_pct(value: Decimal, denominator: Decimal) -> float:
    return _money((value / denominator) * Decimal("100"))


def _top_contribution(values: List[Decimal], total: Decimal, top_n: int) -> Optional[float]:
    if total == 0:
        return None
    return _ratio_pct(sum(values[:top_n], Decimal("0")), total)


def _hhi(values: List[Decimal], total: Decimal) -> Optional[float]:
    if total == 0:
        return None
    return float(sum((value / total) ** 2 for value in values).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _optional_dec(value: Any) -> Optional[Decimal]:
    return Decimal(str(value)) if value is not None else None


def _csv(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _normalise_side(value: Any) -> str:
    side = str(value or "").lower().strip()
    if side == "buy":
        return "long"
    if side == "sell":
        return "short"
    return side


# ── Helpers ────────────────────────────────────────────────────────────────


def _iso_ts(ts: datetime) -> str:
    """Return an ISO-8601 timestamp string normalised to UTC."""
    return _as_utc(ts).isoformat()


def _as_utc(ts: datetime) -> datetime:
    """Treat naive datetimes as UTC and return an aware UTC datetime."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _load_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {timezone_name}") from exc


# ── Journal summary ─────────────────────────────────────────────────────────


async def get_journal_summary(
    session: AsyncSession,
    user_id: int,
    exchange: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregate journal PnL, trade count, and win rate per tag.

    Reads ``TradeJournalEntry`` rows for the user (optionally filtered by
    exchange). Each entry's comma-separated ``tags`` field is split into
    individual tags; every tag receives a full attribution for the entry
    (i.e. an entry tagged ``"scalp,swing"`` contributes to both tags).
    """
    stmt = select(TradeJournalEntry).where(TradeJournalEntry.user_id == user_id)
    if exchange:
        stmt = stmt.where(TradeJournalEntry.exchange == exchange.lower().strip())
    result = await session.execute(stmt)
    entries: List[TradeJournalEntry] = list(result.scalars().all())

    tag_stats: Dict[str, Dict[str, Any]] = {}
    total_entries = len(entries)

    for entry in entries:
        if entry.tags:
            tags = [tag.strip().lower() for tag in entry.tags.split(",") if tag.strip()]
        else:
            tags = ["untagged"]

        for tag in tags:
            bucket = tag_stats.setdefault(
                tag,
                {
                    "trade_count": 0,
                    "total_pnl": 0.0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                },
            )
            bucket["trade_count"] += 1
            if entry.pnl is None:
                continue
            bucket["total_pnl"] += entry.pnl
            if entry.pnl > 0:
                bucket["winning_trades"] += 1
            elif entry.pnl < 0:
                bucket["losing_trades"] += 1

    for bucket in tag_stats.values():
        bucket["total_pnl"] = round(bucket["total_pnl"], 2)
        decisive = bucket["winning_trades"] + bucket["losing_trades"]
        bucket["win_rate"] = (
            round((bucket["winning_trades"] / decisive) * 100, 2) if decisive else 0.0
        )
        bucket["avg_pnl"] = (
            round(bucket["total_pnl"] / bucket["trade_count"], 2)
            if bucket["trade_count"]
            else 0.0
        )

    linked = sum(1 for e in entries if e.position_id is not None)
    insights = _strategy_insights_from_tags(tag_stats, total_entries, linked)
    pos_insights = await _closed_position_concentration_insights(
        session, user_id, exchange
    )
    insights.extend(pos_insights)

    return {
        "total_entries": total_entries,
        "linked_to_position": linked,
        "unlinked_to_position": total_entries - linked,
        "tags": tag_stats,
        "insights": insights,
    }


def _strategy_insights_from_tags(
    tag_stats: Dict[str, Dict[str, Any]],
    total_entries: int,
    linked_to_position: int,
) -> List[Dict[str, Any]]:
    """Descriptive, evidence-based insight cards (Phase 4). Fail closed when empty."""
    insights: List[Dict[str, Any]] = []
    if total_entries == 0:
        return [
            {
                "id": "no_journal_entries",
                "severity": "warning",
                "title": "No journal entries yet",
                "body": "Tag closed trades in the journal to build strategy scorecards.",
                "evidence_tag": None,
                "evidence_count": 0,
                "evidence_href": "/journal",
            }
        ]

    ranked = sorted(
        ((tag, stats) for tag, stats in tag_stats.items() if tag != "untagged"),
        key=lambda item: (item[1]["total_pnl"], item[1]["trade_count"]),
        reverse=True,
    )
    if ranked:
        best_tag, best = ranked[0]
        if best["trade_count"] >= 2 and best["total_pnl"] > 0:
            insights.append(
                {
                    "id": "best_tag_edge",
                    "severity": "positive",
                    "title": f"Repeatable edge candidate: {best_tag}",
                    "body": (
                        f"{best['trade_count']} tagged trades, "
                        f"${best['total_pnl']:.2f} total PnL, "
                        f"{best['win_rate']:.0f}% win rate."
                    ),
                    "evidence_tag": best_tag,
                    "evidence_count": best["trade_count"],
                    "evidence_href": f"/journal?tag={best_tag}",
                }
            )
        worst_tag, worst = ranked[-1]
        if worst["trade_count"] >= 2 and worst["total_pnl"] < 0:
            insights.append(
                {
                    "id": "worst_tag_drag",
                    "severity": "negative",
                    "title": f"Drag on results: {worst_tag}",
                    "body": (
                        f"{worst['trade_count']} tagged trades lost "
                        f"${abs(worst['total_pnl']):.2f} total "
                        f"({worst['win_rate']:.0f}% win rate)."
                    ),
                    "evidence_tag": worst_tag,
                    "evidence_count": worst["trade_count"],
                    "evidence_href": f"/journal?tag={worst_tag}",
                }
            )

    untagged = tag_stats.get("untagged")
    if untagged and total_entries > 0:
        share = (untagged["trade_count"] / total_entries) * 100
        if share >= 40:
            insights.append(
                {
                    "id": "untagged_concentration",
                    "severity": "warning",
                    "title": "High untagged share",
                    "body": (
                        f"{share:.0f}% of journal entries have no strategy tag — "
                        "scorecards stay incomplete until tags are added."
                    ),
                    "evidence_tag": "untagged",
                    "evidence_count": untagged["trade_count"],
                    "evidence_href": "/journal?tag=untagged",
                }
            )

    if total_entries > 0:
        link_share = (linked_to_position / total_entries) * 100
        insights.append(
            {
                "id": "position_journal_link_rate",
                "severity": "neutral" if link_share >= 50 else "warning",
                "title": "Journal ↔ closed-position link rate",
                "body": (
                    f"{linked_to_position} of {total_entries} entries "
                    f"({link_share:.0f}%) are linked to a stored closed position. "
                    "New entries auto-link the newest matching closed position when possible."
                ),
                "evidence_tag": None,
                "evidence_count": linked_to_position,
                "evidence_href": "/journal",
            }
        )

    return insights


async def _closed_position_concentration_insights(
    session: AsyncSession,
    user_id: int,
    exchange: Optional[str],
) -> List[Dict[str, Any]]:
    """Symbol concentration warnings from closed PositionHistory (Phase 4)."""
    stmt = select(PositionHistory).where(PositionHistory.user_id == user_id)
    if exchange:
        stmt = stmt.where(PositionHistory.exchange == exchange.lower().strip())
    result = await session.execute(stmt)
    positions = list(result.scalars().all())
    if len(positions) < 3:
        return []

    by_symbol: Dict[str, Dict[str, Any]] = {}
    for pos in positions:
        sym = (pos.symbol or "UNKNOWN").upper()
        bucket = by_symbol.setdefault(
            sym, {"count": 0, "total_pnl": 0.0, "gross_abs": 0.0}
        )
        pnl = float(pos.pnl or 0.0)
        bucket["count"] += 1
        bucket["total_pnl"] += pnl
        bucket["gross_abs"] += abs(pnl)

    total_abs = sum(b["gross_abs"] for b in by_symbol.values()) or 0.0
    total_trades = len(positions)
    top_sym, top = max(by_symbol.items(), key=lambda kv: kv[1]["gross_abs"])
    share_abs = (top["gross_abs"] / total_abs * 100) if total_abs > 0 else 0.0
    share_n = top["count"] / total_trades * 100

    insights: List[Dict[str, Any]] = []
    if share_abs >= 40 or share_n >= 40:
        insights.append(
            {
                "id": "symbol_pnl_concentration",
                "severity": "warning",
                "title": f"Concentration: {top_sym}",
                "body": (
                    f"{top['count']} of {total_trades} closed trades "
                    f"({share_n:.0f}% by count) and {share_abs:.0f}% of |PnL| mass "
                    f"are in {top_sym} (net ${top['total_pnl']:.2f})."
                ),
                "evidence_tag": None,
                "evidence_count": top["count"],
                "evidence_symbol": top_sym,
                # Deep-link into portfolio Analytics → Closed Positions with symbol filter
                "evidence_href": (
                    f"/portfolio?exchange={exchange or 'mexc'}"
                    f"&tab=analytics&analytics_tab=closed-positions"
                    f"&symbols={top_sym}"
                ),
            }
        )
    return insights
