"""Analytics routes — portfolio performance, equity curve, daily PnL, allocation.

Endpoints
---------
GET /api/v1/analytics/{exchange}/performance   — performance metrics
GET /api/v1/analytics/{exchange}/equity-curve   — equity curve points
GET /api/v1/analytics/{exchange}/daily-pnl      — daily PnL aggregation
GET /api/v1/analytics/{exchange}/allocation     — current asset allocation

All endpoints require JWT auth (``Depends(get_current_user)``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import User
from backend.services import analytics_service
from backend.services.exchange_service import (
    SUPPORTED_EXCHANGES,
    is_ccxt_available,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


# ── Pydantic response models ────────────────────────────────────────────────


class PerformanceMetricsResponse(BaseModel):
    """Response for GET /performance."""

    win_rate: float = Field(description="Percentage of winning trades")
    profit_factor: float | None = Field(
        description="Gross profit / gross loss. None when no losing trades (∞)."
    )
    sharpe_ratio: float | None = Field(
        description="Simplified per-trade Sharpe (mean/std*sqrt(n)). None when < 2 trades."
    )
    max_drawdown: float = Field(description="Largest peak-to-trough decline (USD)")
    max_drawdown_percent: float | None = Field(
        description="Max drawdown as % of peak. None when peak is 0/negative."
    )
    average_win: float = Field(description="Mean PnL of winning trades")
    average_loss: float = Field(description="Mean PnL of losing trades")
    total_trades: int = Field(description="Total closed positions")
    winning_trades: int = Field(description="Count of profitable trades")
    losing_trades: int = Field(description="Count of losing trades")
    best_trade: float = Field(description="Best single trade PnL")
    worst_trade: float = Field(description="Worst single trade PnL")
    total_pnl: float = Field(description="Total realised PnL")
    total_pnl_percent: float = Field(description="Total realised PnL %")


class EquityCurvePoint(BaseModel):
    timestamp: str
    total_value: float


class EquityCurveResponse(BaseModel):
    exchange: str
    points: List[EquityCurvePoint]


class DailyPnlPoint(BaseModel):
    date: str
    pnl: float


class DailyPnlResponse(BaseModel):
    exchange: str
    days: List[DailyPnlPoint]


class AllocationItem(BaseModel):
    asset: str
    usd_value: float
    percentage: float


class AllocationResponse(BaseModel):
    exchange: str
    items: List[AllocationItem]


# ── Risk metrics ─────────────────────────────────────────────────────────


class RiskMetricsResponse(BaseModel):
    """Response for GET /api/v1/analytics/{exchange}/risk."""

    exchange: str
    total_exposure_usd: float = Field(description="Sum of position notional value × leverage exposure")
    net_exposure_usd: float = Field(description="Long USD − Short USD (positive = net long)")
    long_exposure_usd: float
    short_exposure_usd: float
    avg_liquidation_distance_pct: Optional[float] = Field(
        None, description="Average % distance from mark price to liquidation price"
    )
    margin_usage_pct: float = Field(description="Total margin used / total balance (0–100)")
    total_margin_used: float
    total_balance_usd: Optional[float] = None
    open_positions: int
    risk_score: float = Field(description="0–100, higher = more risk")


# ── Journal analytics ──────────────────────────────────────────────────────


class JournalTagStat(BaseModel):
    """Per-tag aggregates inside the journal summary."""

    trade_count: int = Field(description="Number of entries with this tag")
    total_pnl: float = Field(description="Sum of PnL across tagged entries")
    winning_trades: int = Field(description="Entries with PnL > 0")
    losing_trades: int = Field(description="Entries with PnL < 0")
    win_rate: float = Field(description="Win rate (0–100) of decisive trades")


class JournalSummaryResponse(BaseModel):
    """Response for GET /api/v1/analytics/{exchange}/journal-summary."""

    exchange: str
    total_entries: int = Field(description="Total journal entries (all tags)")
    tags: Dict[str, JournalTagStat] = Field(
        default_factory=dict,
        description="Per-tag stats keyed by tag name (lowercased). Untagged entries → 'untagged'.",
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _require_supported_exchange(exchange: str) -> str:
    """Return the normalised exchange slug or raise HTTP 404 / 501."""
    exchange_slug = exchange.strip().lower()
    if not is_ccxt_available():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="ccxt package is not installed — portfolio analytics is disabled",
            headers={"X-Error-Code": "ccxt_not_installed"},
        )
    # Lazy-load supported exchanges
    from backend.services import exchange_service
    exchange_service._load_supported_exchanges()
    if exchange_slug not in SUPPORTED_EXCHANGES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exchange '{exchange_slug}' is not supported. Supported: {sorted(SUPPORTED_EXCHANGES)}",
            headers={"X-Error-Code": "unsupported_exchange"},
        )
    return exchange_slug


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get(
    "/{exchange}/performance",
    response_model=PerformanceMetricsResponse,
    summary="Portfolio performance metrics",
)
async def get_performance_metrics(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PerformanceMetricsResponse:
    """Return win rate, profit factor, Sharpe ratio, max drawdown and other
    trading metrics computed from closed position history.
    """
    exchange_slug = _require_supported_exchange(exchange)
    metrics: Dict[str, Any] = await analytics_service.compute_performance_metrics(
        session, current_user.id, exchange_slug
    )
    return PerformanceMetricsResponse(**metrics)


@router.get(
    "/{exchange}/equity-curve",
    response_model=EquityCurveResponse,
    summary="Portfolio equity curve",
)
async def get_equity_curve(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EquityCurveResponse:
    """Return the portfolio equity curve from snapshot history.

    Each point is ``{timestamp, total_value}``. When ``total_balance_usd`` is
    null for all snapshots, the equity is reconstructed from cumulative
    realised PnL (``total_pnl_usd``).
    """
    exchange_slug = _require_supported_exchange(exchange)
    points = await analytics_service.get_equity_curve(
        session, current_user.id, exchange_slug
    )
    return EquityCurveResponse(
        exchange=exchange_slug,
        points=[EquityCurvePoint(**p) for p in points],
    )


@router.get(
    "/{exchange}/daily-pnl",
    response_model=DailyPnlResponse,
    summary="Daily PnL aggregation",
)
async def get_daily_pnl(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DailyPnlResponse:
    """Return PnL aggregated by close-time date.

    Each point is ``{date, pnl}`` where date is ``YYYY-MM-DD``.
    """
    exchange_slug = _require_supported_exchange(exchange)
    days = await analytics_service.get_daily_pnl(
        session, current_user.id, exchange_slug
    )
    return DailyPnlResponse(
        exchange=exchange_slug,
        days=[DailyPnlPoint(**d) for d in days],
    )


@router.get(
    "/{exchange}/allocation",
    response_model=AllocationResponse,
    summary="Current asset allocation",
)
async def get_allocation(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AllocationResponse:
    """Return current asset allocation from the latest balance rows.

    Each item is ``{asset, usd_value, percentage}``. Returns an empty list
    when no USD values are populated.
    """
    exchange_slug = _require_supported_exchange(exchange)
    items = await analytics_service.get_allocation(
        session, current_user.id, exchange_slug
    )
    return AllocationResponse(
        exchange=exchange_slug,
        items=[AllocationItem(**i) for i in items],
    )


@router.get(
    "/{exchange}/risk",
    response_model=RiskMetricsResponse,
    summary="Portfolio risk metrics",
)
async def get_risk_metrics(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RiskMetricsResponse:
    """Compute real-time risk metrics from open positions + balances.

    Returns total leverage exposure, net long/short exposure, average
    liquidation distance, margin usage, and a 0–100 risk score.
    """
    exchange_slug = _require_supported_exchange(exchange)

    from sqlalchemy import select

    from backend.models import (
        PortfolioBalance,
        PortfolioPosition,
        PortfolioSnapshot,
    )

    # ── Load positions ──────────────────────────────────────────────
    result = await session.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.user_id == current_user.id,
            PortfolioPosition.exchange == exchange_slug,
        )
    )
    positions = list(result.scalars().all())

    # ── Load balances (for margin-usage denominator) ────────────────
    bal_result = await session.execute(
        select(PortfolioBalance).where(
            PortfolioBalance.user_id == current_user.id,
            PortfolioBalance.exchange == exchange_slug,
        )
    )
    balances = list(bal_result.scalars().all())

    # ── Compute exposure metrics ────────────────────────────────────
    long_exposure = 0.0
    short_exposure = 0.0
    total_margin_used = 0.0
    liq_distances: list[float] = []

    for p in positions:
        side = (p.side or "").upper()
        # Notional position value in USD (mark price × size × contract size)
        contract_size = float(p.contract_size or 1.0)
        size = float(p.size or 0.0)
        mark = float(p.mark_price or 0.0)
        notional = abs(size) * abs(mark) * contract_size
        margin = float(p.margin or 0.0)
        total_margin_used += margin

        if side in ("LONG", "BUY"):
            long_exposure += notional
        elif side in ("SHORT", "SELL"):
            short_exposure += notional

        # Liquidation distance
        liq = p.liquidation_price
        if liq is not None and mark > 0:
            liq_f = float(liq)
            if liq_f > 0:
                distance_pct = abs(mark - liq_f) / mark * 100.0
                liq_distances.append(distance_pct)

    total_exposure_usd = long_exposure + short_exposure
    net_exposure_usd = long_exposure - short_exposure
    avg_liq_distance = (
        sum(liq_distances) / len(liq_distances) if liq_distances else None
    )

    # ── Total balance (USD) ────────────────────────────────────────
    # Use the sum of balance USD values (stablecoin-heavy portfolios).
    total_balance_usd: Optional[float] = None
    for b in balances:
        usd_val = getattr(b, "usd_value", None)
        if usd_val is not None:
            if total_balance_usd is None:
                total_balance_usd = 0.0
            total_balance_usd += float(usd_val)

    # ── Margin usage percentage ────────────────────────────────────
    if total_balance_usd and total_balance_usd > 0:
        margin_usage_pct = min(100.0, (total_margin_used / total_balance_usd) * 100.0)
    else:
        margin_usage_pct = 0.0

    # ── Risk score (0–100) ─────────────────────────────────────────
    risk_score = _compute_risk_score(
        total_exposure_usd=total_exposure_usd,
        net_exposure_usd=net_exposure_usd,
        total_balance_usd=total_balance_usd,
        margin_usage_pct=margin_usage_pct,
        avg_liq_distance=avg_liq_distance,
        open_positions=len(positions),
    )

    return RiskMetricsResponse(
        exchange=exchange_slug,
        total_exposure_usd=round(total_exposure_usd, 2),
        net_exposure_usd=round(net_exposure_usd, 2),
        long_exposure_usd=round(long_exposure, 2),
        short_exposure_usd=round(short_exposure, 2),
        avg_liquidation_distance_pct=(
            round(avg_liq_distance, 2) if avg_liq_distance is not None else None
        ),
        margin_usage_pct=round(margin_usage_pct, 2),
        total_margin_used=round(total_margin_used, 2),
        total_balance_usd=(
            round(total_balance_usd, 2) if total_balance_usd is not None else None
        ),
        open_positions=len(positions),
        risk_score=round(risk_score, 1),
    )


def _compute_risk_score(
    total_exposure_usd: float,
    net_exposure_usd: float,
    total_balance_usd: Optional[float],
    margin_usage_pct: float,
    avg_liq_distance: Optional[float],
    open_positions: int,
) -> float:
    """Compute a 0–100 risk score (higher = more risk).

    Weighted blend of:
      * Leverage ratio (exposure / balance)
      * Margin usage %
      * Liquidation proximity (closer = riskier)
      * Concentration (single position = riskier)
    """
    score = 0.0

    # 1. Leverage ratio (exposure / balance) — 35 points max
    if total_balance_usd and total_balance_usd > 0:
        lev_ratio = total_exposure_usd / total_balance_usd
        # 0x → 0, 5x → 35, 10x+ → 35
        lev_points = min(35.0, lev_ratio * 7.0)
    else:
        # No balance data — infer from exposure alone (capped)
        lev_points = min(20.0, total_exposure_usd / 1000.0)
    score += lev_points

    # 2. Margin usage — 30 points max
    # 0% → 0, 50% → 15, 80% → 24, 100% → 30
    usage_points = min(30.0, margin_usage_pct * 0.3)
    score += usage_points

    # 3. Liquidation proximity — 25 points max
    if avg_liq_distance is not None:
        # < 2% → 25, 5% → 15, 10% → 5, 20%+ → 0
        if avg_liq_distance < 2.0:
            liq_points = 25.0
        elif avg_liq_distance < 5.0:
            liq_points = 25.0 - (avg_liq_distance - 2.0) * (10.0 / 3.0)
        elif avg_liq_distance < 20.0:
            liq_points = max(0.0, 15.0 - (avg_liq_distance - 5.0) * (15.0 / 15.0))
        else:
            liq_points = 0.0
        score += liq_points

    # 4. Net exposure skew — 10 points max
    # Fully one-sided (100% long or 100% short) = more risk
    if total_exposure_usd > 0:
        skew = abs(net_exposure_usd) / total_exposure_usd
        score += skew * 10.0

    return min(100.0, max(0.0, score))


@router.get(
    "/{exchange}/journal-summary",
    response_model=JournalSummaryResponse,
    summary="Trading journal tag summary (PnL, count, win rate per tag)",
)
async def get_journal_summary_route(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JournalSummaryResponse:
    """Aggregate trading-journal entries by tag for the given exchange.

    Returns total_entries plus a ``tags`` map keyed by lowercased tag name.
    Each tag bucket contains trade_count, total_pnl, winning_trades,
    losing_trades, and win_rate. Entries with no tags are grouped under
    ``"untagged"``.

    Unlike other analytics endpoints, this route does NOT require a
    supported exchange (ccxt) — journal entries can be created for manual /
    unconnected exchanges, so we accept any slug and normalise it.
    """
    exchange_slug = exchange.strip().lower()
    summary = await analytics_service.get_journal_summary(
        session, current_user.id, exchange_slug
    )
    return JournalSummaryResponse(
        exchange=exchange_slug,
        total_entries=summary.get("total_entries", 0),
        tags={
            tag: JournalTagStat(**stats)
            for tag, stats in summary.get("tags", {}).items()
        },
    )
