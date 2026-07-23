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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PortfolioBalance, PortfolioSnapshot, PositionHistory, TradeJournalEntry

logger = logging.getLogger(__name__)


# ── Performance metrics ─────────────────────────────────────────────────────


async def compute_performance_metrics(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Dict[str, Any]:
    """Compute trading performance metrics from closed positions.

    Phase 0 only supports closed-position realised PnL reconstruction. Account
    return, conventional account-equity drawdown, and conventional Sharpe remain
    unavailable until capital/equity history is complete.
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

    if total_trades == 0:
        return _empty_metrics()

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

    return {
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "trade_quality_score": rounded_trade_quality,
        "trade_quality_basis": "per_trade_pnl_dispersion",
        "realised_pnl_drawdown_usd": rounded_drawdown_usd,
        "realised_pnl_drawdown_pct": rounded_drawdown_pct,
        "drawdown_basis": "cumulative_closed_pnl",
        "account_equity_drawdown_usd": None,
        "account_equity_drawdown_pct": None,
        "account_equity_drawdown_reason": "capital_history_missing",
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
        "total_pnl_percent": None,
        "total_pnl_percent_reason": "capital_history_missing",
        "account_return_pct": None,
        "account_return_pct_reason": "capital_history_missing",
        "source": "PositionHistory.pnl",
        "basis": "closed_position_reconstruction",
        "complete": False,
        "unavailable_reason": "capital_history_missing",
    }


def _empty_metrics() -> Dict[str, Any]:
    """Return metrics with unsupported account-return fields marked unavailable."""
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
        "account_equity_drawdown_reason": "capital_history_missing",
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
        "total_pnl_percent_reason": "capital_history_missing",
        "account_return_pct": None,
        "account_return_pct_reason": "capital_history_missing",
        "source": "PositionHistory.pnl",
        "basis": "closed_position_reconstruction",
        "complete": False,
        "unavailable_reason": "capital_history_missing",
    }


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


# ── Equity curve ────────────────────────────────────────────────────────────


async def get_equity_curve(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Dict[str, Any]:
    """Return account-equity points from ``PortfolioSnapshot.total_balance_usd``.

    Null snapshot balances are omitted. Phase 0 does not fallback to unrealised
    PnL or realised-PnL reconstruction because those are not account equity.
    """
    result = await session.execute(
        select(PortfolioSnapshot)
        .where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.exchange == exchange,
        )
        .order_by(PortfolioSnapshot.timestamp.asc())
    )
    snapshots: List[PortfolioSnapshot] = list(result.scalars().all())

    points: List[Dict[str, Any]] = []
    for snapshot in snapshots:
        if snapshot.total_balance_usd is None:
            continue
        points.append(
            {
                "timestamp": _iso_ts(snapshot.timestamp),
                "total_value": round(float(snapshot.total_balance_usd), 2),
                "basis": "account_snapshot",
            }
        )

    has_null_snapshots = any(snapshot.total_balance_usd is None for snapshot in snapshots)
    if not points:
        return {
            "points": [],
            "basis": None,
            "source": "PortfolioSnapshot.total_balance_usd",
            "complete": False,
            "unavailable_reason": "no_account_equity_data",
        }

    return {
        "points": points,
        "basis": "account_snapshot",
        "source": "PortfolioSnapshot.total_balance_usd",
        "complete": not has_null_snapshots,
        "unavailable_reason": None,
    }


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

    return {"total_entries": total_entries, "tags": tag_stats}
