"""Portfolio analytics service — performance metrics, equity curve, daily PnL, allocation.

All functions are async and accept an ``AsyncSession`` so they can be called
directly from route handlers. They read from the already-cached
``PositionHistory``, ``PortfolioSnapshot`` and ``PortfolioBalance`` tables
(no outbound exchange API calls).

Math is done with the Python standard library (``statistics``, ``math``) so
no extra numeric dependencies are required.
"""

from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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

    Returns a dict with:
      win_rate, profit_factor, sharpe_ratio, max_drawdown, max_drawdown_percent,
      average_win, average_loss, total_trades, winning_trades, losing_trades,
      best_trade, worst_trade, total_pnl, total_pnl_percent.
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

    pnls = [p.pnl for p in positions]
    pnl_pcts = [p.pnl_percent for p in positions]

    winning = [p for p in pnls if p > 0]
    losing = [p for p in pnls if p < 0]
    # Break-even trades (pnl == 0) count as neither win nor loss for win-rate,
    # but they ARE included in total_trades. Following common convention,
    # break-even is excluded from win_rate denominator only if there are
    # winning or losing trades; otherwise included as neutral.
    winning_trades = len(winning)
    losing_trades = len(losing)

    # Win rate: wins / total closed positions (excluding break-even from the
    # denominator would be another convention; we use wins/total for clarity).
    win_rate = (winning_trades / total_trades) * 100 if total_trades else 0.0

    # Profit factor: gross_profit / abs(gross_loss)
    gross_profit = sum(winning)
    gross_loss = abs(sum(losing))  # positive number
    profit_factor: Optional[float]
    if gross_loss == 0:
        profit_factor = None  # no losing trades → "∞" on the frontend
    else:
        profit_factor = gross_profit / gross_loss

    # Average win / loss
    average_win = statistics.mean(winning) if winning else 0.0
    average_loss = statistics.mean(losing) if losing else 0.0

    # Best / worst trade
    best_trade = max(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0

    # Total PnL
    total_pnl = sum(pnls)
    total_pnl_percent = sum(pnl_pcts)

    # Sharpe ratio (simplified, per-trade): mean(pnl) / std(pnl) * sqrt(n)
    sharpe_ratio: Optional[float] = None
    if len(pnls) >= 2:
        std_pnl = statistics.stdev(pnls)
        if std_pnl != 0:
            mean_pnl = statistics.mean(pnls)
            sharpe_ratio = (mean_pnl / std_pnl) * math.sqrt(len(pnls))

    # Max drawdown: largest peak-to-trough decline in cumulative PnL
    max_drawdown, max_drawdown_percent = _compute_max_drawdown(pnls)

    return {
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "sharpe_ratio": round(sharpe_ratio, 4) if sharpe_ratio is not None else None,
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_percent": round(max_drawdown_percent, 2) if max_drawdown_percent is not None else None,
        "average_win": round(average_win, 2),
        "average_loss": round(average_loss, 2),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "best_trade": round(best_trade, 2),
        "worst_trade": round(worst_trade, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_percent": round(total_pnl_percent, 2),
    }


def _empty_metrics() -> Dict[str, Any]:
    """Return a metrics dict with zeroed / None values when no trades exist."""
    return {
        "win_rate": 0.0,
        "profit_factor": None,
        "sharpe_ratio": None,
        "max_drawdown": 0.0,
        "max_drawdown_percent": None,
        "average_win": 0.0,
        "average_loss": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "best_trade": 0.0,
        "worst_trade": 0.0,
        "total_pnl": 0.0,
        "total_pnl_percent": 0.0,
    }


def _compute_max_drawdown(pnls: List[float]) -> tuple[float, Optional[float]]:
    """Compute the largest peak-to-trough decline in cumulative PnL.

    Walks the cumulative PnL series, tracking the running peak. At each step
    the drawdown is ``peak - cumulative``. Returns ``(max_drawdown_abs,
    max_drawdown_pct)`` where the percentage is relative to the peak (or
    ``None`` when the peak is zero / negative).

    A positive ``max_drawdown_abs`` means the portfolio dropped by that many
    USD from its highest cumulative-PnL point to the subsequent trough.
    """
    if not pnls:
        return 0.0, None

    cumulative = 0.0
    peak = 0.0  # start at 0 (no trades yet → equity baseline)
    max_dd = 0.0
    max_dd_pct: Optional[float] = None

    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown
            if peak > 0:
                max_dd_pct = (drawdown / peak) * 100
            else:
                max_dd_pct = None

    return max_dd, max_dd_pct


# ── Equity curve ────────────────────────────────────────────────────────────


async def get_equity_curve(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[Dict[str, Any]]:
    """Return ``[{timestamp, total_value}]`` from PortfolioSnapshot history.

    ``total_value`` is ``total_balance_usd`` when available, otherwise falls
    back to the cumulative realised PnL reconstructed from PositionHistory.

    Snapshots are ordered by timestamp ascending so the curve reads
    left-to-right chronologically.
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

    if not snapshots:
        return []

    # Check whether any snapshot has a non-null total_balance_usd.
    has_balance = any(s.total_balance_usd is not None for s in snapshots)

    points: List[Dict[str, Any]] = []
    if has_balance:
        # Use total_balance_usd, falling back to forward-filled last known
        # value for snapshots where it was None.
        last_value: Optional[float] = None
        for s in snapshots:
            val = s.total_balance_usd
            if val is not None:
                last_value = val
            points.append({
                "timestamp": _iso_ts(s.timestamp),
                "total_value": round(last_value, 2) if last_value is not None else 0.0,
            })
    else:
        # No balance data — reconstruct equity from cumulative PnL.
        # Build a map of timestamp → running cumulative pnl.
        pnls = await _cumulative_pnl_by_timestamp(session, user_id, exchange)
        # Align cumulative PnL to snapshot timestamps.
        cumulative = 0.0
        # Sort snapshot timestamps; for each, sum pnls up to that timestamp.
        for s in snapshots:
            ts = s.timestamp
            # Add all trade pnls closed at or before this snapshot timestamp.
            # (pnls list is pre-sorted; we track a cursor.)
            # Simpler: use the snapshot's own total_pnl_usd as the equity proxy.
            cumulative = s.total_pnl_usd
            points.append({
                "timestamp": _iso_ts(ts),
                "total_value": round(cumulative, 2),
            })

    return points


# ── Daily PnL ───────────────────────────────────────────────────────────────


async def get_daily_pnl(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[Dict[str, Any]]:
    """Aggregate PositionHistory PnL by close_time date.

    Returns ``[{date, pnl}]`` sorted ascending, where ``date`` is
    ``YYYY-MM-DD``.
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

    daily: Dict[str, float] = {}
    for p in positions:
        if p.close_time is None:
            continue
        # Normalise to date string (UTC).
        ct = p.close_time
        if ct.tzinfo is not None:
            ct = ct.astimezone(timezone.utc).replace(tzinfo=None)
        date_str = ct.strftime("%Y-%m-%d")
        daily[date_str] = daily.get(date_str, 0.0) + p.pnl

    return [
        {"date": date, "pnl": round(pnl, 2)}
        for date, pnl in sorted(daily.items())
    ]


# ── Allocation ─────────────────────────────────────────────────────────────


async def get_allocation(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[Dict[str, Any]]:
    """Compute current asset allocation from the latest PortfolioBalance rows.

    Returns ``[{asset, usd_value, percentage}]`` sorted by USD value descending.
    Balances with zero or null USD value are excluded. When all ``usd_value``
    entries are null, an empty list is returned (frontend shows connect prompt).
    """
    result = await session.execute(
        select(PortfolioBalance)
        .where(
            PortfolioBalance.user_id == user_id,
            PortfolioBalance.exchange == exchange,
        )
    )
    balances: List[PortfolioBalance] = list(result.scalars().all())

    if not balances:
        return []

    # Check if any usd_value is populated.
    has_usd = any(b.usd_value is not None and b.usd_value > 0 for b in balances)
    if not has_usd:
        return []

    items: List[Dict[str, Any]] = []
    total_usd = 0.0
    for b in balances:
        val = b.usd_value
        if val is None or val <= 0:
            continue
        items.append({"asset": b.asset, "usd_value": round(val, 2)})
        total_usd += val

    for item in items:
        item["percentage"] = round((item["usd_value"] / total_usd) * 100, 2) if total_usd > 0 else 0.0

    items.sort(key=lambda x: x["usd_value"], reverse=True)
    return items


# ── Helpers ────────────────────────────────────────────────────────────────


def _iso_ts(ts: datetime) -> str:
    """Return an ISO-8601 timestamp string (UTC)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


async def _cumulative_pnl_by_timestamp(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[tuple[datetime, float]]:
    """Return running cumulative PnL at each trade close_time (for equity fallback)."""
    result = await session.execute(
        select(PositionHistory.close_time, PositionHistory.pnl)
        .where(
            PositionHistory.user_id == user_id,
            PositionHistory.exchange == exchange,
        )
        .order_by(PositionHistory.close_time.asc().nullslast())
    )
    rows = result.all()
    cumulative = 0.0
    out: List[tuple[datetime, float]] = []
    for close_time, pnl in rows:
        if close_time is None:
            continue
        cumulative += pnl
        out.append((close_time, cumulative))
    return out


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

    Returns::

        {
          "total_entries": int,
          "tags": {
            "scalp": {
              "trade_count": int,
              "total_pnl": float,
              "winning_trades": int,
              "losing_trades": int,
              "win_rate": float,   # 0–100
            },
            ...
          }
        }

    Entries with no tags are grouped under the special key ``"untagged"``.
    Entries with a ``null`` ``pnl`` are counted toward ``trade_count`` but do
    not contribute to PnL, win, loss, or win_rate figures.
    """
    stmt = select(TradeJournalEntry).where(TradeJournalEntry.user_id == user_id)
    if exchange:
        stmt = stmt.where(TradeJournalEntry.exchange == exchange.lower().strip())
    result = await session.execute(stmt)
    entries: List[TradeJournalEntry] = list(result.scalars().all())

    tag_stats: Dict[str, Dict[str, Any]] = {}
    total_entries = len(entries)

    for e in entries:
        # Split the tags string into individual, normalised tag names.
        if e.tags:
            tags = [t.strip().lower() for t in e.tags.split(",") if t.strip()]
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
            if e.pnl is None:
                # Entries without PnL are counted but excluded from PnL math.
                continue
            bucket["total_pnl"] += e.pnl
            if e.pnl > 0:
                bucket["winning_trades"] += 1
            elif e.pnl < 0:
                bucket["losing_trades"] += 1

    # Round totals and compute win rates (wins / (wins + losses)).
    for bucket in tag_stats.values():
        bucket["total_pnl"] = round(bucket["total_pnl"], 2)
        decisive = bucket["winning_trades"] + bucket["losing_trades"]
        bucket["win_rate"] = (
            round((bucket["winning_trades"] / decisive) * 100, 2) if decisive else 0.0
        )

    return {"total_entries": total_entries, "tags": tag_stats}
