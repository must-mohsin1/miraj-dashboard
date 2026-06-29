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
    created_at: datetime

    model_config = {"from_attributes": True}


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
