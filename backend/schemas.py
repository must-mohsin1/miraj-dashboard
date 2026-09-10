"""Pydantic schemas for request/response validation."""

import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ── Auth ────────────────────────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserLoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    detail: str


# ── Collector public reports ────────────────────────────────────────────────


class CollectorPublicModel(BaseModel):
    """Base for persisted collector data: every object has an explicit allowlist."""

    model_config = {"extra": "forbid"}


class CollectorGate(CollectorPublicModel):
    label: str = Field(..., min_length=1, max_length=128)
    state: Literal["passed", "blocked", "pending", "unavailable"]
    reason: Optional[str] = Field(default=None, max_length=512)


class CollectorVerdict(CollectorPublicModel):
    state: Literal["NO_TRADE", "WATCH", "READY_LONG", "READY_SHORT", "INVALIDATED", "STALE"]
    summary: str = Field(..., min_length=1, max_length=1024)
    gates: list[CollectorGate] = Field(default_factory=list, max_length=16)


class CollectorQuote(CollectorPublicModel):
    price: Optional[float] = None
    as_of: Optional[datetime] = None
    context_only: bool


class CollectorScore(CollectorPublicModel):
    label: str = Field(..., min_length=1, max_length=128)
    value: Optional[float] = None
    maximum: Optional[float] = None
    detail: Optional[str] = Field(default=None, max_length=512)


class CollectorCandle(CollectorPublicModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


class CollectorLevelRange(CollectorPublicModel):
    low: float
    high: float


class CollectorEmaMetrics(CollectorPublicModel):
    ema_20: Optional[float] = Field(default=None, alias="20")
    ema_50: Optional[float] = Field(default=None, alias="50")
    ema_200: Optional[float] = Field(default=None, alias="200")


class CollectorBollingerMetrics(CollectorPublicModel):
    width_pct: Optional[float] = None
    mean_width_pct: Optional[float] = None
    squeeze: Optional[bool] = None


class CollectorTimeframeSummary(CollectorPublicModel):
    completed_count: Optional[int] = None
    first_completed_open_utc: Optional[datetime] = None
    completed_rows_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)
    close: Optional[float] = None
    close_time_utc: Optional[datetime] = None
    open_time_utc: Optional[datetime] = None
    rsi14: Optional[float] = None
    ema: Optional[CollectorEmaMetrics] = None
    last_volume_base: Optional[float] = None
    volume20_base: Optional[float] = None
    high20: Optional[float] = None
    low20: Optional[float] = None
    bollinger: Optional[CollectorBollingerMetrics] = None
    volume_vs20: Optional[float] = None


class CollectorTimeframe(CollectorPublicModel):
    timeframe: str = Field(..., min_length=1, max_length=32)
    state: str = Field(..., min_length=1, max_length=64)
    close: Optional[float] = None
    as_of: Optional[datetime] = None
    candles: list[CollectorCandle] = Field(default_factory=list, max_length=64)
    fvg: Optional[CollectorLevelRange] = None
    ote: Optional[CollectorLevelRange] = None
    metrics: Optional[CollectorTimeframeSummary] = None


class CollectorSourceHealth(CollectorPublicModel):
    source: str = Field(..., min_length=1, max_length=128)
    status: Literal["ok", "degraded", "failed", "unavailable"]
    checked_at: Optional[datetime] = None
    fallback: bool
    detail: Optional[str] = Field(default=None, max_length=512)


class CollectorSetupState(CollectorPublicModel):
    state: Literal["S0", "S1", "S2", "S3", "S4", "S5"]
    status: Literal["passed", "blocked", "pending", "unavailable"]
    label: str = Field(..., min_length=1, max_length=128)
    reason: Optional[str] = Field(default=None, max_length=512)


class CollectorReportIngestRequest(CollectorPublicModel):
    """Strict, public-only payload accepted from the authenticated collector."""

    report_id: str = Field(..., min_length=1, max_length=128)
    payload_sha256: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime
    symbol: str = Field(..., min_length=1, max_length=40)
    venue: str = Field(..., min_length=1, max_length=64)
    source: str = Field(..., min_length=1, max_length=128)
    schema_version: str = Field(..., min_length=1, max_length=32)
    verdict: CollectorVerdict
    quote: CollectorQuote
    scores: list[CollectorScore] = Field(default_factory=list, max_length=32)
    timeframes: list[CollectorTimeframe] = Field(default_factory=list, max_length=16)
    source_health: list[CollectorSourceHealth] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)
    setup_states: list[CollectorSetupState] = Field(..., min_length=6, max_length=6)

    @field_validator("setup_states")
    @classmethod
    def setup_states_must_be_ordered_and_complete(cls, value: list[CollectorSetupState]) -> list[CollectorSetupState]:
        if [state.state for state in value] != ["S0", "S1", "S2", "S3", "S4", "S5"]:
            raise ValueError("setup_states must contain S0 through S5 in order")
        return value

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value


class CollectorLatestReportResponse(BaseModel):
    status: Literal["received", "validated", "stale", "failed", "unavailable"]
    stale: bool
    received_at: Optional[datetime] = None
    report: Optional[dict[str, Any]] = None


class CollectorReportResponse(CollectorLatestReportResponse):
    idempotent: Optional[bool] = None


# ── Analysis ────────────────────────────────────────────────────────────────

class AnalysisCreateRequest(BaseModel):
    pair: str = Field(..., min_length=1, max_length=20)
    analysis_type: str = Field(..., max_length=64)
    parameters: Optional[dict[str, Any]] = None


class AnalysisResponse(BaseModel):
    id: int
    user_id: int
    pair: str
    analysis_type: str
    parameters: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Watchlist ───────────────────────────────────────────────────────────────

class WatchlistPairCreateRequest(BaseModel):
    pair: str = Field(..., min_length=1, max_length=20)


class WatchlistPairResponse(BaseModel):
    id: int
    user_id: int
    pair: str
    sort_order: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class WatchlistReorderRequest(BaseModel):
    pair_ids: list[int] = Field(..., min_length=1, description="Ordered list of pair database IDs")


class WatchlistPairWithScore(BaseModel):
    """Watchlist pair enriched with the latest scan score and status."""

    id: int
    user_id: int
    pair: str
    sort_order: int = 0
    created_at: datetime
    score: Optional[float] = Field(None, ge=0, le=100)
    status: str = "Active"
    market_scope: str = "research_only"
    mexc_symbol: Optional[str] = None

    model_config = {"from_attributes": True}


class WatchlistListResponse(BaseModel):
    """Paginated wrapper for GET /api/v1/watchlist."""

    total: int
    pairs: list[WatchlistPairWithScore]


class WatchlistRemoveResponse(BaseModel):
    detail: str = "Pair removed"


# ── Decision Desk ───────────────────────────────────────────────────────────

class DecisionDeskWatchlistPair(BaseModel):
    pair: str
    market_scope: str
    mexc_symbol: Optional[str] = None


class DecisionDeskSetupAnalysis(BaseModel):
    entry: float
    invalidation: float
    target_one: float
    risk_reward: float
    swing_high: float
    swing_low: float


class DecisionDeskSignal(BaseModel):
    pair: str
    direction: str
    state: str
    missing_gates: list[str]
    analysis: Optional[DecisionDeskSetupAnalysis] = None
    created_at: datetime
    updated_at: datetime


class DecisionDeskNotificationChannel(BaseModel):
    channel_type: str
    enabled: bool
    configured: bool
    updated_at: datetime


class DecisionDeskNotificationOutboxItem(BaseModel):
    pair: str
    direction: str
    signal_state: str
    channel_type: str
    status: str
    attempts: int
    created_at: datetime
    next_attempt_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    error: Optional[str] = None


class DecisionDeskAccountPosition(BaseModel):
    symbol: str
    side: str
    size: float


class DecisionDeskAccountReconciliation(BaseModel):
    exchange: str
    freshness: str
    last_reconciled_at: Optional[datetime] = None
    positions: list[DecisionDeskAccountPosition] = Field(default_factory=list)


class DecisionDeskResponse(BaseModel):
    generated_at: datetime
    watchlist: list[DecisionDeskWatchlistPair]
    signals: list[DecisionDeskSignal]
    notification_channels: list[DecisionDeskNotificationChannel]
    notification_outbox: list[DecisionDeskNotificationOutboxItem]
    account_reconciliation: list[DecisionDeskAccountReconciliation]


# ── Pair Settings ───────────────────────────────────────────────────────────

class PairSettingsUpdateRequest(BaseModel):
    pair: str = Field(..., min_length=1, max_length=20)
    settings: dict[str, Any]


class PairSettingsResponse(BaseModel):
    id: int
    user_id: int
    pair: str
    settings: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
