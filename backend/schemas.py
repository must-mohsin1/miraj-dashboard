"""Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


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
