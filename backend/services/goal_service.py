"""Monthly profit-goal progress from futures equity + capital flow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import FuturesAccountSnapshot, MonthlyProfitGoal
from backend.services.phase3_account_return import (
    _external_coverage,
    _load_equity_snapshots,
    _load_external_flows,
    _pick_series_endpoints,
)

DEFAULT_TZ = "Asia/Karachi"
DEFAULT_EXCHANGE = "mexc"


def month_bounds(now: datetime, tz_name: str = DEFAULT_TZ) -> tuple[int, int, datetime, datetime]:
    """Return year, month, inclusive-start UTC, exclusive-end UTC for the local month."""
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=timezone.utc).astimezone(tz)
    start_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_local.month == 12:
        end_local = start_local.replace(year=start_local.year + 1, month=1)
    else:
        end_local = start_local.replace(month=start_local.month + 1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_local.year, start_local.month, start_utc, end_utc


def period_bounds(year: int, month: int, tz_name: str = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """Return inclusive-start/exclusive-end UTC bounds for a local calendar month."""
    tz = ZoneInfo(tz_name)
    start_local = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        end_local = datetime(year, month + 1, 1, tzinfo=tz)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def _as_naive_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(timezone.utc).replace(tzinfo=None)


async def compute_month_progress(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    *,
    start_utc: datetime,
    end_utc: datetime,
    base_equity: Optional[float] = None,
) -> dict[str, Any]:
    coverage = await _external_coverage(session, user_id, exchange)
    if not coverage["ok"]:
        return {
            "available": False,
            "reason": coverage["reason"],
            "opening_equity": base_equity,
            "ending_equity": None,
            "net_external_flows": None,
            "net_profit": None,
            "return_pct": None,
        }

    snapshots = await _load_equity_snapshots(session, user_id, exchange)
    in_month = [
        s for s in snapshots
        if s.source_ts is not None and start_utc <= _as_naive_utc(s.source_ts) < end_utc
    ]
    if not in_month:
        return {
            "available": False,
            "reason": "opening_equity_missing",
            "opening_equity": base_equity,
            "ending_equity": None,
            "net_external_flows": None,
            "net_profit": None,
            "return_pct": None,
        }

    endpoints = _pick_series_endpoints(in_month)
    if endpoints is None:
        return {
            "available": False,
            "reason": "insufficient_equity_snapshots",
            "opening_equity": base_equity,
            "ending_equity": None,
            "net_external_flows": None,
            "net_profit": None,
            "return_pct": None,
        }

    opening, ending = endpoints
    snapshot_opening_eq = float(opening.equity or 0.0)
    opening_eq = float(base_equity) if base_equity is not None else float(opening.equity or 0.0)
    ending_eq = float(ending.equity or 0.0)
    if abs(snapshot_opening_eq) <= 1e-8 or abs(opening_eq) <= 1e-8:
        return {
            "available": False,
            "reason": "futures_equity_flat",
            "opening_equity": opening_eq,
            "ending_equity": ending_eq,
            "net_external_flows": None,
            "net_profit": None,
            "return_pct": None,
        }

    flows = await _load_external_flows(
        session, user_id, exchange, _as_naive_utc(opening.source_ts), _as_naive_utc(ending.source_ts)
    )
    net_external = sum(float(f.signed_amount or 0.0) for f in flows)
    net_profit = ending_eq - opening_eq - net_external
    return_pct = ((ending_eq - net_external) / opening_eq - 1.0) * 100.0
    return {
        "available": True,
        "reason": None,
        "opening_equity": round(opening_eq, 4),
        "ending_equity": round(ending_eq, 4),
        "net_external_flows": round(net_external, 4),
        "net_profit": round(net_profit, 4),
        "return_pct": round(return_pct, 4),
        "as_of": ending.source_ts.isoformat() if ending.source_ts else None,
    }


def _bucket_key(snapshot: FuturesAccountSnapshot, resolution: str, tz: ZoneInfo) -> str:
    local = _as_naive_utc(snapshot.source_ts).replace(tzinfo=timezone.utc).astimezone(tz)
    if resolution == "day":
        return local.strftime("%Y-%m-%d")
    if resolution == "week":
        iso = local.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if resolution == "month":
        return local.strftime("%Y-%m")
    raise ValueError(f"Unsupported resolution: {resolution}")


def _profit_buckets(
    snapshots: Sequence[FuturesAccountSnapshot],
    flows: Sequence[Any],
    *,
    resolution: str,
    tz: ZoneInfo,
    base_equity: Optional[float],
) -> list[dict[str, Any]]:
    """Build additive equity-profit buckets using consecutive snapshot endpoints."""
    endpoints: list[tuple[str, FuturesAccountSnapshot]] = []
    for snapshot in snapshots:
        key = _bucket_key(snapshot, resolution, tz)
        if endpoints and endpoints[-1][0] == key:
            endpoints[-1] = (key, snapshot)
        else:
            endpoints.append((key, snapshot))

    first = snapshots[0]
    previous_ts = _as_naive_utc(first.source_ts)
    previous_equity = float(base_equity) if base_equity is not None else float(first.equity or 0.0)
    rows: list[dict[str, Any]] = []
    for period, ending in endpoints:
        ending_ts = _as_naive_utc(ending.source_ts)
        bucket_flows = [
            flow for flow in flows
            if flow.occurred_at is not None
            and previous_ts < _as_naive_utc(flow.occurred_at) <= ending_ts
        ]
        net_external = sum(float(flow.signed_amount or 0.0) for flow in bucket_flows)
        ending_equity = float(ending.equity or 0.0)
        net_profit = ending_equity - previous_equity - net_external
        return_pct = None
        if abs(previous_equity) > 1e-8:
            return_pct = ((ending_equity - net_external) / previous_equity - 1.0) * 100.0
        rows.append(
            {
                "period": period,
                "from": previous_ts.isoformat() + "Z",
                "to": ending_ts.isoformat() + "Z",
                "opening_equity": round(previous_equity, 4),
                "ending_equity": round(ending_equity, 4),
                "net_external_flows": round(net_external, 4),
                "net_profit": round(net_profit, 4),
                "return_pct": round(return_pct, 4) if return_pct is not None else None,
            }
        )
        previous_ts = ending_ts
        previous_equity = ending_equity
    return rows


async def compute_period_analytics(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    *,
    start_utc: datetime,
    end_utc: datetime,
    base_equity: Optional[float] = None,
    tz_name: str = DEFAULT_TZ,
) -> dict[str, Any]:
    """Return day/week/month account-profit buckets for one open goal month."""
    coverage = await _external_coverage(session, user_id, exchange)
    if not coverage["ok"]:
        return {
            "available": False,
            "reason": coverage["reason"],
            "basis": "cash_flow_adjusted_futures_equity",
            "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
            "daily": [],
            "weekly": [],
            "monthly": [],
        }

    snapshots = await _load_equity_snapshots(session, user_id, exchange)
    in_month = [
        snapshot for snapshot in snapshots
        if snapshot.source_ts is not None
        and start_utc <= _as_naive_utc(snapshot.source_ts) < end_utc
    ]
    if not in_month:
        return {
            "available": False,
            "reason": "opening_equity_missing",
            "basis": "cash_flow_adjusted_futures_equity",
            "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
            "daily": [],
            "weekly": [],
            "monthly": [],
        }

    endpoints = _pick_series_endpoints(in_month)
    if endpoints is None:
        return {
            "available": False,
            "reason": "insufficient_equity_snapshots",
            "basis": "cash_flow_adjusted_futures_equity",
            "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
            "daily": [],
            "weekly": [],
            "monthly": [],
        }

    opening, ending = endpoints
    snapshot_opening_equity = float(opening.equity or 0.0)
    opening_equity = (
        float(base_equity) if base_equity is not None else snapshot_opening_equity
    )
    if abs(snapshot_opening_equity) <= 1e-8 or abs(opening_equity) <= 1e-8:
        return {
            "available": False,
            "reason": "futures_equity_flat",
            "basis": "cash_flow_adjusted_futures_equity",
            "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
            "daily": [],
            "weekly": [],
            "monthly": [],
        }

    flows = await _load_external_flows(
        session,
        user_id,
        exchange,
        _as_naive_utc(opening.source_ts),
        _as_naive_utc(ending.source_ts),
    )
    opening_index = in_month.index(opening)
    ending_index = in_month.index(ending)
    selected_snapshots = in_month[opening_index:ending_index + 1]
    if len(selected_snapshots) < 2:
        return {
            "available": False,
            "reason": "insufficient_equity_snapshots",
            "basis": "cash_flow_adjusted_futures_equity",
            "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
            "daily": [],
            "weekly": [],
            "monthly": [],
        }
    tz = ZoneInfo(tz_name)
    common = {
        "snapshots": selected_snapshots,
        "flows": flows,
        "tz": tz,
        "base_equity": base_equity,
    }
    return {
        "available": True,
        "reason": None,
        "basis": "cash_flow_adjusted_futures_equity",
        "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
        "daily": _profit_buckets(resolution="day", **common),
        "weekly": _profit_buckets(resolution="week", **common),
        "monthly": _profit_buckets(resolution="month", **common),
    }


async def get_period_goal(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    year: int,
    month: int,
) -> Optional[MonthlyProfitGoal]:
    return (
        await session.execute(
            select(MonthlyProfitGoal).where(
                MonthlyProfitGoal.user_id == user_id,
                MonthlyProfitGoal.exchange == exchange,
                MonthlyProfitGoal.period_year == year,
                MonthlyProfitGoal.period_month == month,
            )
        )
    ).scalar_one_or_none()


async def upsert_open_goal(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    *,
    target_return_pct: float,
    redeem_pct: float,
    base_equity: Optional[float] = None,
    now: Optional[datetime] = None,
    tz_name: str = DEFAULT_TZ,
) -> MonthlyProfitGoal:
    if target_return_pct <= 0 or target_return_pct > 500:
        raise ValueError("target_return_pct must be between 0 exclusive and 500")
    if redeem_pct < 0 or redeem_pct > 100:
        raise ValueError("redeem_pct must be between 0 and 100")
    clock = now or datetime.now(timezone.utc)
    year, month, start_utc, end_utc = month_bounds(clock, tz_name)
    row = await get_period_goal(session, user_id, exchange, year, month)
    progress = await compute_month_progress(
        session, user_id, exchange, start_utc=start_utc, end_utc=end_utc, base_equity=base_equity
    )
    locked_base = base_equity if base_equity is not None else progress.get("opening_equity")
    if row is None:
        row = MonthlyProfitGoal(
            user_id=user_id,
            exchange=exchange,
            period_year=year,
            period_month=month,
            timezone=tz_name,
            target_return_pct=target_return_pct,
            base_equity=locked_base,
            base_source="user_override" if base_equity is not None else "snapshot",
            redeem_pct=redeem_pct,
            reinvest_pct=100.0 - redeem_pct,
            status="open",
        )
        session.add(row)
    else:
        if row.status != "open":
            raise ValueError("Cannot edit a closed month")
        row.target_return_pct = target_return_pct
        row.redeem_pct = redeem_pct
        row.reinvest_pct = 100.0 - redeem_pct
        if base_equity is not None:
            row.base_equity = base_equity
            row.base_source = "user_override"
        row.updated_at = datetime.utcnow()
    await session.flush()
    return row


async def close_stale_goals(
    session: AsyncSession,
    user_id: int,
    exchange: str = DEFAULT_EXCHANGE,
    *,
    now: Optional[datetime] = None,
    tz_name: str = DEFAULT_TZ,
) -> list[MonthlyProfitGoal]:
    """Close prior-month open goals once, leaving unavailable periods untouched."""
    clock = now or datetime.now(timezone.utc)
    current_year, current_month, _, _ = month_bounds(clock, tz_name)
    result = await session.execute(
        select(MonthlyProfitGoal)
        .where(
            MonthlyProfitGoal.user_id == user_id,
            MonthlyProfitGoal.exchange == exchange,
            MonthlyProfitGoal.status == "open",
            or_(
                MonthlyProfitGoal.period_year < current_year,
                and_(
                    MonthlyProfitGoal.period_year == current_year,
                    MonthlyProfitGoal.period_month < current_month,
                ),
            ),
        )
        .order_by(MonthlyProfitGoal.period_year, MonthlyProfitGoal.period_month)
        .with_for_update()
    )
    closed: list[MonthlyProfitGoal] = []
    for goal in result.scalars().all():
        start_utc, end_utc = period_bounds(
            int(goal.period_year),
            int(goal.period_month),
            goal.timezone or tz_name,
        )
        progress = await compute_month_progress(
            session,
            user_id,
            exchange,
            start_utc=start_utc,
            end_utc=end_utc,
            base_equity=goal.base_equity,
        )
        # Capital/snapshot gaps cannot be turned into an immutable declaration.
        if not progress["available"]:
            continue

        net_profit = float(progress["net_profit"])
        distributable_profit = max(net_profit, 0.0)
        declared_redeem = distributable_profit * (float(goal.redeem_pct) / 100.0)
        declared_reinvest = distributable_profit - declared_redeem
        closed_at = _as_naive_utc(clock if clock.tzinfo else clock.replace(tzinfo=timezone.utc))

        goal.status = "closed"
        goal.closed_at = closed_at
        goal.closing_equity = float(progress["ending_equity"])
        goal.net_external_flows = float(progress["net_external_flows"])
        goal.net_profit = net_profit
        goal.realized_return_pct = float(progress["return_pct"])
        goal.declared_redeem_usd = round(declared_redeem, 4)
        goal.declared_reinvest_usd = round(declared_reinvest, 4)
        goal.updated_at = closed_at
        closed.append(goal)

    if closed:
        await session.flush()
    return closed


async def get_year_archive(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    year: int,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(MonthlyProfitGoal)
        .where(
            MonthlyProfitGoal.user_id == user_id,
            MonthlyProfitGoal.exchange == exchange,
            MonthlyProfitGoal.period_year == year,
            MonthlyProfitGoal.status == "closed",
        )
        .order_by(MonthlyProfitGoal.period_month)
    )
    return [
        {
            "period_year": int(goal.period_year),
            "period_month": int(goal.period_month),
            "status": goal.status,
            "target_return_pct": float(goal.target_return_pct),
            "realized_return_pct": (
                float(goal.realized_return_pct)
                if goal.realized_return_pct is not None
                else None
            ),
            "net_profit": float(goal.net_profit) if goal.net_profit is not None else None,
            "declared_redeem_usd": (
                float(goal.declared_redeem_usd)
                if goal.declared_redeem_usd is not None
                else None
            ),
            "declared_reinvest_usd": (
                float(goal.declared_reinvest_usd)
                if goal.declared_reinvest_usd is not None
                else None
            ),
            "closed_at": goal.closed_at.isoformat() + "Z" if goal.closed_at else None,
        }
        for goal in result.scalars().all()
    ]


async def snapshot_now(
    session: AsyncSession,
    user_id: int,
    exchange: str = DEFAULT_EXCHANGE,
    *,
    now: Optional[datetime] = None,
    tz_name: str = DEFAULT_TZ,
) -> dict[str, Any]:
    clock = now or datetime.now(timezone.utc)
    year, month, start_utc, end_utc = month_bounds(clock, tz_name)
    goal = await get_period_goal(session, user_id, exchange, year, month)
    progress = await compute_month_progress(
        session,
        user_id,
        exchange,
        start_utc=start_utc,
        end_utc=end_utc,
        base_equity=goal.base_equity if goal else None,
    )
    if goal is None or goal.status != "open":
        period_analytics = {
            "available": False,
            "reason": "goal_not_set",
            "basis": "cash_flow_adjusted_futures_equity",
            "source": "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount",
            "daily": [],
            "weekly": [],
            "monthly": [],
        }
    else:
        period_analytics = await compute_period_analytics(
            session,
            user_id,
            exchange,
            start_utc=start_utc,
            end_utc=end_utc,
            base_equity=goal.base_equity,
            tz_name=tz_name,
        )
    year_archive = await get_year_archive(session, user_id, exchange, year)
    target = float(goal.target_return_pct) if goal else None
    opening = progress.get("opening_equity")
    target_usd = None
    remaining_usd = None
    if target is not None and opening:
        target_usd = opening * (target / 100.0)
        if progress.get("net_profit") is not None:
            remaining_usd = target_usd - float(progress["net_profit"])
    now_naive = _as_naive_utc(clock if clock.tzinfo else clock.replace(tzinfo=timezone.utc))
    days_left = max(int((end_utc - now_naive).total_seconds() // 86400), 0)

    state = "NO_GOAL"
    if goal is None:
        display = "Set this month's goal."
    elif not progress["available"]:
        state = "UNAVAILABLE"
        display = "Account return is unavailable."
    elif progress["return_pct"] is not None and target is not None:
        if progress["return_pct"] >= target:
            state = "AHEAD"
            display = "Ahead of the monthly goal."
        else:
            state = "BEHIND"
            display = "Behind the monthly goal."
    else:
        state = "UNAVAILABLE"
        display = "Account return is unavailable."

    return {
        "exchange": exchange,
        "timezone": tz_name,
        "period_year": year,
        "period_month": month,
        "goal": None if goal is None else {
            "target_return_pct": goal.target_return_pct,
            "base_equity": goal.base_equity,
            "base_source": goal.base_source,
            "redeem_pct": goal.redeem_pct,
            "reinvest_pct": goal.reinvest_pct,
            "status": goal.status,
        },
        "progress": progress,
        "target_usd": round(target_usd, 4) if target_usd is not None else None,
        "remaining_usd": round(remaining_usd, 4) if remaining_usd is not None else None,
        "period_analytics": period_analytics,
        "year_archive": year_archive,
        "days_left": days_left,
        "state": state,
        "display": display,
    }
