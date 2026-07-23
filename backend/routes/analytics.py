"""Analytics routes — portfolio performance, equity curve, daily PnL, allocation.

Endpoints
---------
GET /api/v1/analytics/{exchange}/performance   — performance metrics
GET /api/v1/analytics/{exchange}/equity-curve   — equity curve points
GET /api/v1/analytics/{exchange}/daily-pnl      — daily PnL aggregation
GET /api/v1/analytics/{exchange}/allocation     — current asset allocation
GET /api/v1/analytics/{exchange}/risk           — real-time risk metrics
GET /api/v1/analytics/{exchange}/health        — portfolio health score + grade
GET /api/v1/analytics/benchmark                — BTC benchmark; account-return comparison unavailable in Phase 0

All endpoints require JWT auth (``Depends(get_current_user)``).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import (
    PortfolioPosition,
    PortfolioSnapshot,
    PositionHistory,
    User,
)
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
    trade_quality_score: float | None = Field(None, description="Per-trade PnL dispersion score; not conventional Sharpe.")
    trade_quality_basis: str = Field(description="Basis for trade_quality_score.")
    realised_pnl_drawdown_usd: float = Field(description="Drawdown of cumulative closed-position PnL in USD.")
    realised_pnl_drawdown_pct: float | None = Field(description="Drawdown of cumulative closed-position PnL as % of peak.")
    drawdown_basis: str = Field(description="Basis for realised drawdown.")
    account_equity_drawdown_usd: float | None = None
    account_equity_drawdown_pct: float | None = None
    account_equity_drawdown_reason: str | None = None
    sharpe_ratio: float | None = Field(None, description="Backward-compatible alias of trade_quality_score.")
    max_drawdown: float = Field(description="Backward-compatible alias of realised_pnl_drawdown_usd.")
    max_drawdown_percent: float | None = Field(description="Backward-compatible alias of realised_pnl_drawdown_pct.")
    average_win: float = Field(description="Mean PnL of winning trades")
    average_loss: float = Field(description="Mean PnL of losing trades")
    total_trades: int = Field(description="Total closed positions")
    winning_trades: int = Field(description="Count of profitable trades")
    losing_trades: int = Field(description="Count of losing trades")
    best_trade: float = Field(description="Best single trade PnL")
    worst_trade: float = Field(description="Worst single trade PnL")
    total_pnl: float = Field(description="Dollar sum of MEXC-reported closed-position PnL")
    total_pnl_basis: str = Field(description="Basis/source for total_pnl.")
    total_pnl_percent: float | None = Field(None, description="Unavailable until capital history exists.")
    total_pnl_percent_reason: str | None = None
    account_return_pct: float | None = None
    account_return_pct_reason: str | None = None
    source: str | None = None
    basis: str | None = None
    complete: bool = False
    unavailable_reason: str | None = None


class EquityCurvePoint(BaseModel):
    timestamp: str
    total_value: float
    basis: str | None = None


class EquityCurveResponse(BaseModel):
    exchange: str
    points: List[EquityCurvePoint]
    basis: str | None = None
    source: str | None = None
    complete: bool = False
    unavailable_reason: str | None = None


class DailyPnlPoint(BaseModel):
    date: str
    pnl: float


class DailyPnlResponse(BaseModel):
    exchange: str
    days: List[DailyPnlPoint]
    timezone: str = "UTC"
    period: Dict[str, str | None] = Field(default_factory=dict)
    source: str | None = None
    basis: str | None = None
    complete: bool = False
    unavailable_reason: str | None = None


class AllocationItem(BaseModel):
    asset: str
    usd_value: float
    percentage: float
    account_type: str = "spot"


class AllocationResponse(BaseModel):
    exchange: str
    account_type: str = "spot"
    items: List[AllocationItem]
    source: str | None = None
    basis: str | None = None
    complete: bool = False
    unavailable_reason: str | None = None


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
    margin_usage_pct: Optional[float] = Field(None, description="Total margin used / futures equity (0–100); null when unavailable")
    total_margin_used: float
    total_balance_usd: Optional[float] = None
    open_positions: int
    risk_score: Optional[float] = Field(None, description="0–100, higher = more risk; null when not applicable")
    risk_reason: Optional[str] = None
    unavailable_reason: Optional[str] = None


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


# ── Scan accuracy (trade attribution by confluence score band) ────────────────


class ScanAccuracyBand(BaseModel):
    """Win-rate / avg-PnL stats for a single confluence-score band."""

    score_band: str = Field(description="Score range label, e.g. '20-25'")
    total_trades: int = Field(description="Closed trades whose pre-entry scan scored in this band")
    winning_trades: int = Field(description="Profitable trades in this band")
    win_rate: float = Field(description="Win rate (0–100)")
    avg_pnl: float = Field(description="Mean PnL across trades in this band")


class ScanAccuracyResponse(BaseModel):
    """Response for `GET /api/v1/analytics/{exchange}/scan-accuracy`."""

    exchange: str
    total_trades: int = Field(description="Total closed positions linked to a pre-entry scan")
    bands: List[ScanAccuracyBand]


# ── Portfolio health score ─────────────────────────────────────────────────


class HealthScoreResponse(BaseModel):
    """Response for GET /api/v1/analytics/{exchange}/health.

    ``health_score`` is a 0–100 weighted blend where higher = healthier
    (lower risk). The component risk metrics (``correlation_risk``,
    ``concentration_risk``) are 0–100 where higher = more risk, while
    ``diversification_score`` is 0–100 where higher = more diversified.
    """

    exchange: str
    diversification_score: float = Field(
        description="0–100. Higher = more diversified (1 asset = 0, 3+ = 50+, even distribution = bonus)."
    )
    correlation_risk: float = Field(
        description="0–100. Higher = more directional correlation (all long or all short = 100)."
    )
    concentration_risk: float = Field(
        description="0–100. Higher = more concentration (one asset > 50% of portfolio = high)."
    )
    health_score: Optional[float] = Field(
        description="0–100 weighted average (lower risk = higher health)."
    )
    grade: Optional[str] = Field(None, description="Letter grade: A / B / C / D / F, or null when not applicable.")
    health_reason: Optional[str] = None
    recommendations: List[str] = Field(
        default_factory=list,
        description="Actionable recommendations to improve portfolio health.",
    )
    open_positions: int = Field(description="Number of open positions.")
    unique_assets: int = Field(description="Number of unique symbols held.")


# ── Benchmark comparison ───────────────────────────────────────────────────


class BenchmarkPoint(BaseModel):
    """A single day's benchmark return data point."""

    date: str
    btc_return_pct: float = Field(description="BTC cumulative return % from start (indexed).")
    portfolio_return_pct: Optional[float] = Field(
        None,
        description="Unavailable in Phase 0 because closed-position PnL is not account return.",
    )


class BenchmarkResponse(BaseModel):
    """Response for GET /api/v1/analytics/benchmark."""

    symbol: str
    days: int
    btc_return_pct: float = Field(description="Total BTC cumulative return % over the period.")
    portfolio_return_pct: Optional[float] = Field(
        None,
        description="Unavailable in Phase 0 because capital history is missing.",
    )
    alpha: Optional[float] = Field(None, description="Unavailable until account return exists.")
    beta: Optional[float] = Field(
        None,
        description="Unavailable until account return exists.",
    )
    points: List[BenchmarkPoint] = Field(
        default_factory=list,
        description="Daily BTC indexed series; account-return series remains null in Phase 0.",
    )
    source: str | None = None
    basis: str | None = None
    complete: bool = False
    unavailable_reason: str | None = None


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
    """Return realised closed-position PnL performance metrics.

    Metrics include win rate, profit factor, MEXC-reported ``total_pnl``,
    ``trade_quality_score`` from per-trade PnL dispersion, and
    ``realised_pnl_drawdown_*`` from cumulative closed-position PnL. Account
    return and account-equity drawdown remain unavailable until complete
    account equity/capital history exists.
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
    """Return account equity curve points from snapshot history.

    Each point is ``{timestamp, total_value}`` and is emitted only from a
    snapshot with non-null ``total_balance_usd``. When no account-equity
    snapshots are available, the response returns ``points=[]`` with
    ``source=PortfolioSnapshot.total_balance_usd``, ``complete=False``, and
    ``unavailable_reason=no_account_equity_data``.
    """
    exchange_slug = _require_supported_exchange(exchange)
    curve = await analytics_service.get_equity_curve(
        session, current_user.id, exchange_slug
    )
    return EquityCurveResponse(
        exchange=exchange_slug,
        points=[EquityCurvePoint(**p) for p in curve["points"]],
        basis=curve.get("basis"),
        source=curve.get("source"),
        complete=curve.get("complete", False),
        unavailable_reason=curve.get("unavailable_reason"),
    )


@router.get(
    "/{exchange}/daily-pnl",
    response_model=DailyPnlResponse,
    summary="Daily PnL aggregation",
)
async def get_daily_pnl(
    exchange: str,
    timezone_name: str = Query("UTC", alias="timezone"),
    from_: Optional[datetime] = Query(None, alias="from"),
    to_: Optional[datetime] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DailyPnlResponse:
    """Return PnL aggregated by close-time date.

    Each point is ``{date, pnl}`` where date is ``YYYY-MM-DD``.
    """
    exchange_slug = _require_supported_exchange(exchange)
    try:
        daily = await analytics_service.get_daily_pnl(
            session,
            current_user.id,
            exchange_slug,
            timezone_name=timezone_name,
            from_ts=from_,
            to_ts=to_,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DailyPnlResponse(
        exchange=exchange_slug,
        days=[DailyPnlPoint(**d) for d in daily["days"]],
        timezone=daily["timezone"],
        period=daily["period"],
        source=daily.get("source"),
        basis=daily.get("basis"),
        complete=daily.get("complete", False),
        unavailable_reason=daily.get("unavailable_reason"),
    )


@router.get(
    "/{exchange}/allocation",
    response_model=AllocationResponse,
    summary="Current asset allocation",
)
async def get_allocation(
    exchange: str,
    account_type: str = Query("spot", pattern="^(spot|futures)$"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AllocationResponse:
    """Return current asset allocation from the latest balance rows.

    Each item is ``{asset, usd_value, percentage}``. Returns an empty list
    when no USD values are populated.
    """
    exchange_slug = _require_supported_exchange(exchange)
    allocation = await analytics_service.get_allocation(
        session, current_user.id, exchange_slug, account_type=account_type
    )
    return AllocationResponse(
        exchange=exchange_slug,
        account_type=allocation["account_type"],
        items=[AllocationItem(**i) for i in allocation["items"]],
        source=allocation.get("source"),
        basis=allocation.get("basis"),
        complete=allocation.get("complete", False),
        unavailable_reason=allocation.get("unavailable_reason"),
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

    # ── Load positions ──────────────────────────────────────────────
    result = await session.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.user_id == current_user.id,
            PortfolioPosition.exchange == exchange_slug,
        )
    )
    positions = list(result.scalars().all())

    if not positions:
        return RiskMetricsResponse(
            exchange=exchange_slug,
            total_exposure_usd=0.0,
            net_exposure_usd=0.0,
            long_exposure_usd=0.0,
            short_exposure_usd=0.0,
            avg_liquidation_distance_pct=None,
            margin_usage_pct=None,
            total_margin_used=0.0,
            total_balance_usd=None,
            open_positions=0,
            risk_score=None,
            risk_reason="no_open_futures_risk",
            unavailable_reason="futures_equity_not_available",
        )

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

    # Phase 0 has no futures-equity snapshot table. Spot balances must not be
    # used as the futures-collateral denominator, so margin usage remains null.
    total_balance_usd: Optional[float] = None
    margin_usage_pct: Optional[float] = None

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
        margin_usage_pct=round(margin_usage_pct, 2) if margin_usage_pct is not None else None,
        total_margin_used=round(total_margin_used, 2),
        total_balance_usd=(
            round(total_balance_usd, 2) if total_balance_usd is not None else None
        ),
        open_positions=len(positions),
        risk_score=round(risk_score, 1),
        risk_reason=None,
        unavailable_reason="futures_equity_not_available",
    )


def _compute_risk_score(
    total_exposure_usd: float,
    net_exposure_usd: float,
    total_balance_usd: Optional[float],
    margin_usage_pct: Optional[float],
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
    if margin_usage_pct is not None:
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


def _health_grade(score: float) -> str:
    """Map a 0–100 health score to a letter grade A/B/C/D/F."""
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "F"


def _compute_diversification_score(
    num_assets: int,
    weights: list[float],
) -> float:
    """Compute a 0–100 diversification score.

    * 1 asset → 0
    * 2 assets → 30
    * 3+ assets → baseline 50, scaling up toward 100 as count grows
    * Bonus for even distribution (Herfindahl-Hirschman index).
    """
    if num_assets <= 0:
        return 0.0
    if num_assets == 1:
        return 0.0
    if num_assets == 2:
        base = 30.0
    else:
        # 3 → 50, 4 → 60, 5 → 67, 6+ ramps toward ~80
        base = min(80.0, 40.0 + (num_assets - 2) * 10.0)

    # Evenness bonus (0–20): use HHI where 1/n is perfectly even (hhi=1/n).
    total = sum(weights)
    if total <= 0:
        return round(base, 1)
    shares = [w / total for w in weights]
    hhi = sum(s * s for s in shares)
    even = 1.0 / num_assets
    if hhi <= 0:
        evenness = 1.0
    else:
        # Ratio: 1.0 when perfectly even (hhi == even), → 0 as concentrated.
        evenness = max(0.0, min(1.0, even / hhi))
    bonus = evenness * 20.0
    return round(min(100.0, base + bonus), 1)


def _compute_correlation_risk(positions: list[PortfolioPosition]) -> float:
    """Compute 0–100 directional correlation risk.

    If all positions are the same direction (all long or all short), risk = 100.
    Mixed directions reduce the score proportional to the minority share.
    """
    if not positions:
        return 0.0
    long_n = sum(1 for p in positions if (p.side or "").upper() in ("LONG", "BUY"))
    short_n = sum(1 for p in positions if (p.side or "").upper() in ("SHORT", "SELL"))
    total = long_n + short_n
    if total == 0:
        return 0.0
    if long_n == 0 or short_n == 0:
        return 100.0
    minority = min(long_n, short_n) / total
    # 50% mixed → 0, fully one-sided → 100
    return round((1.0 - minority / 0.5) * 100.0, 1)


def _compute_concentration_risk(
    positions: list[PortfolioPosition],
) -> tuple[float, Optional[str]]:
    """Compute 0–100 concentration risk + the dominant symbol (if any).

    Uses notional USD value (mark_price × |size| × contract_size).
    Returns (risk_score, dominant_symbol).
    """
    if not positions:
        return 0.0, None
    notionals: dict[str, float] = {}
    for p in positions:
        contract_size = float(p.contract_size or 1.0)
        size = float(p.size or 0.0)
        mark = float(p.mark_price or 0.0)
        notional = abs(size) * abs(mark) * contract_size
        sym = (p.symbol or "").upper()
        notionals[sym] = notionals.get(sym, 0.0) + notional
    total = sum(notionals.values())
    if total <= 0:
        return 0.0, None
    max_share = max(notionals.values()) / total
    dominant = max(notionals, key=notionals.get)
    # 100% in one asset → 100; 50% → 50 threshold; below 20% → low (~0-15)
    if max_share >= 1.0:
        risk = 100.0
    elif max_share >= 0.5:
        # 50% → 50, 100% → 100 (linear)
        risk = 50.0 + (max_share - 0.5) * 100.0
    elif max_share >= 0.2:
        # 20% → 15, 50% → 50
        risk = 15.0 + (max_share - 0.2) * (35.0 / 0.3)
    else:
        # < 20% → 0 to 15
        risk = max_share / 0.2 * 15.0
    return round(min(100.0, risk), 1), dominant


@router.get(
    "/{exchange}/health",
    response_model=HealthScoreResponse,
    summary="Portfolio health score & grade",
)
async def get_health_score(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HealthScoreResponse:
    """Compute a portfolio health score (0–100, higher = healthier).

    Weighted blend of:
      * Diversification score (higher = better, weight 0.35)
      * Correlation risk (higher = worse, weight 0.30)
      * Concentration risk (higher = worse, weight 0.35)

    A letter grade (A/B/C/D/F) is derived from the health score, plus
    actionable recommendations to improve it.
    """
    exchange_slug = _require_supported_exchange(exchange)

    snapshot_result = await session.execute(
        select(PortfolioSnapshot)
        .where(
            PortfolioSnapshot.user_id == current_user.id,
            PortfolioSnapshot.exchange == exchange_slug,
        )
        .order_by(PortfolioSnapshot.timestamp.desc())
        .limit(1)
    )
    latest_snapshot = snapshot_result.scalar_one_or_none()
    if latest_snapshot is None:
        return HealthScoreResponse(
            exchange=exchange_slug,
            diversification_score=0.0,
            correlation_risk=0.0,
            concentration_risk=0.0,
            health_score=None,
            grade=None,
            health_reason="no_snapshot_data",
            recommendations=[],
            open_positions=0,
            unique_assets=0,
        )
    if latest_snapshot.open_positions == 0:
        return HealthScoreResponse(
            exchange=exchange_slug,
            diversification_score=0.0,
            correlation_risk=0.0,
            concentration_risk=0.0,
            health_score=None,
            grade=None,
            health_reason="no_open_positions",
            recommendations=["No open futures risk."],
            open_positions=0,
            unique_assets=0,
        )

    # ── Load open positions ─────────────────────────────────────────
    result = await session.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.user_id == current_user.id,
            PortfolioPosition.exchange == exchange_slug,
        )
    )
    positions = list(result.scalars().all())

    unique_symbols = {(p.symbol or "").upper() for p in positions}
    num_assets = len(unique_symbols)

    # Diversification
    per_symbol_notional: dict[str, float] = {}
    for p in positions:
        contract_size = float(p.contract_size or 1.0)
        size = float(p.size or 0.0)
        mark = float(p.mark_price or 0.0)
        notional = abs(size) * abs(mark) * contract_size
        sym = (p.symbol or "").upper()
        per_symbol_notional[sym] = per_symbol_notional.get(sym, 0.0) + notional
    weights = list(per_symbol_notional.values()) if per_symbol_notional else [0.0]
    diversification = _compute_diversification_score(num_assets, weights)

    # Correlation risk
    correlation = _compute_correlation_risk(positions)

    # Concentration risk
    concentration, dominant = _compute_concentration_risk(positions)

    # ── Health score (higher = healthier = lower risk) ─────────────
    # health = diversification * 0.35 + (100 - correlation) * 0.30 + (100 - concentration) * 0.35
    health = (
        diversification * 0.35
        + (100.0 - correlation) * 0.30
        + (100.0 - concentration) * 0.35
    )
    health = round(min(100.0, max(0.0, health)), 1)
    grade = _health_grade(health)

    # ── Recommendations ──────────────────────────────────────────────
    recommendations: list[str] = []
    if num_assets == 0:
        recommendations.append("No open positions detected — open positions to begin building a portfolio.")
    elif num_assets == 1:
        recommendations.append("Hold at least 3 different assets to improve diversification (currently 1).")
    elif num_assets == 2:
        recommendations.append("Consider adding a 3rd asset — diversification score is moderate.")
    if correlation >= 70 and positions:
        long_n = sum(1 for p in positions if (p.side or "").upper() in ("LONG", "BUY"))
        short_n = sum(1 for p in positions if (p.side or "").upper() in ("SHORT", "SELL"))
        if long_n > short_n and short_n == 0:
            recommendations.append("Add a short position to reduce directional correlation risk.")
        elif short_n > long_n and long_n == 0:
            recommendations.append("Add a long position to reduce directional correlation risk.")
        else:
            recommendations.append("Diversify position directions (mix of long/short) to lower correlation risk.")
    if concentration >= 50 and dominant:
        recommendations.append(f"Reduce {dominant} allocation below 50% to lower concentration risk.")
    if health >= 80:
        recommendations.append("Portfolio is well-balanced — maintain current diversification.")
    elif not recommendations:
        recommendations.append("Consider rebalancing to improve the overall health score.")

    return HealthScoreResponse(
        exchange=exchange_slug,
        diversification_score=diversification,
        correlation_risk=correlation,
        concentration_risk=concentration,
        health_score=health,
        grade=grade,
        health_reason=None,
        recommendations=recommendations,
        open_positions=len(positions),
        unique_assets=num_assets,
    )


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


@router.get(
    "/{exchange}/scan-accuracy",
    response_model=ScanAccuracyResponse,
    summary="Scan accuracy by confluence-score band",
)
async def get_scan_accuracy(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ScanAccuracyResponse:
    """Compute win rate and average PnL per confluence-score band.

    Links every closed position to the nearest scan that ran at or before
    its ``open_time`` (same linking logic as the ``trade-attribution``
    endpoint), then buckets trades by their pre-entry scan's confluence
    score into 5-point-wide bands (0-5, 5-10, 10-15, 15-20, 20-25, 25-30).

    For each band returns: ``total_trades``, ``winning_trades``,
    ``win_rate`` (0-100), and ``avg_pnl``. Bands with no trades are still
    included (with zeroed stats) so the chart always has 6 bars.

    Requires a supported exchange (ccxt) for slug validation, like the
    other analytics routes.
    """
    exchange_slug = _require_supported_exchange(exchange)

    from backend.services.scan_attribution_service import (
        compute_scan_accuracy,
        link_positions_to_scans,
    )

    linked = await link_positions_to_scans(
        session, current_user.id, exchange_slug
    )
    bands = compute_scan_accuracy(linked)
    total_linked = sum(b["total_trades"] for b in bands)
    return ScanAccuracyResponse(
        exchange=exchange_slug,
        total_trades=total_linked,
        bands=[ScanAccuracyBand(**b) for b in bands],
    )


# ── Benchmark comparison ────────────────────────────────────────────────────


def _fetch_btc_daily_closes(symbol: str, days: int) -> list[tuple[str, float]]:
    """Fetch BTC-USD daily closes for the last ``days`` via yfinance.

    Returns a list of ``(date_str "YYYY-MM-DD", close_price)`` tuples sorted
    ascending. Returns an empty list on failure.
    """
    try:
        import yfinance as yf  # noqa: PLC0415
    except ImportError:
        logger.warning("yfinance not installed — benchmark endpoint unavailable")
        return []

    # yfinance period: fetch ~2x the days to ensure enough data after weekends/holidays.
    period = f"{max(days, 30)}d"
    try:
        df = yf.download(symbol, period=period, interval="1d", progress=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance download failed for %s: %s", symbol, exc)
        return []

    if df is None or df.empty:
        return []

    # Flatten MultiIndex columns if present (yfinance >= 0.2.31).
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df.dropna(how="all", inplace=True)

    out: list[tuple[str, float]] = []
    for ts, row in df.iterrows():
        close = row.get("Close")
        if close is None or (isinstance(close, float) and math.isnan(close)):
            continue
        # ts is a pandas Timestamp; normalise to date string YYYY-MM-DD.
        try:
            date_str = ts.strftime("%Y-%m-%d")
        except AttributeError:
            date_str = str(ts)[:10]
        out.append((date_str, float(close)))

    # Sort ascending by date and trim to requested days.
    out.sort(key=lambda x: x[0])
    if len(out) > days:
        out = out[-days:]
    return out


@router.get(
    "/benchmark",
    response_model=BenchmarkResponse,
    summary="Benchmark comparison: BTC return; account-return comparison unavailable in Phase 0",
)
async def get_benchmark(
    symbol: str = Query("BTC-USD", description="yfinance ticker for the benchmark asset"),
    days: int = Query(30, ge=1, le=365, description="Number of days to compare (1–365)"),
    exchange: str = Query(
        "mexc",
        description="Exchange slug whose portfolio history to compare against.",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BenchmarkResponse:
    """Fetch BTC buy-and-hold benchmark data.

    * Fetches ``symbol`` (default BTC-USD) daily closes for the last ``days``
      days via yfinance and computes cumulative return % indexed to 0 at start.

    Phase 0 intentionally does not compute account/portfolio return, alpha, or
    beta from ``PositionHistory`` closed-position PnL. Those fields stay null
    with ``capital_history_missing`` until complete account equity/cash-flow
    history exists.
    """
    # ── 1. Fetch BTC daily closes ──────────────────────────────────
    btc_closes = _fetch_btc_daily_closes(symbol, days)

    # Build BTC cumulative return % series indexed to 0% at the first point.
    btc_series: dict[str, float] = {}
    if btc_closes:
        base_close = btc_closes[0][1]
        for date_str, close in btc_closes:
            if base_close > 0:
                ret_pct = (close / base_close - 1.0) * 100.0
            else:
                ret_pct = 0.0
            btc_series[date_str] = round(ret_pct, 4)

    # ── 2. Return BTC points only; account-return comparison is unavailable.
    all_dates = sorted(btc_series.keys())
    points: list[BenchmarkPoint] = []
    for d in all_dates:
        points.append(
            BenchmarkPoint(
                date=d,
                btc_return_pct=round(btc_series[d], 4),
                portfolio_return_pct=None,
            )
        )

    # ── 3. Summary stats: BTC only; account-return fields remain unavailable.
    btc_total = btc_series.get(all_dates[-1], 0.0) if all_dates else 0.0

    return BenchmarkResponse(
        symbol=symbol,
        days=days,
        btc_return_pct=round(btc_total, 4),
        portfolio_return_pct=None,
        alpha=None,
        beta=None,
        points=points,
        source="PortfolioSnapshot.total_balance_usd",
        basis=None,
        complete=False,
        unavailable_reason="capital_history_missing",
    )
