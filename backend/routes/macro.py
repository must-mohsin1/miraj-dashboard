"""Macro data route — returns cached macro market data points."""

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.models import User
from backend.services.macro_service import build_response, is_stale, refresh_macro_data

router = APIRouter(prefix="/api/v1", tags=["macro"])


# ── Response models ────────────────────────────────────────────────────────


class FundingRateEntry(BaseModel):
    """A single asset's funding rate from Binance Futures."""

    symbol: str = Field(..., description='Display symbol, e.g. "BTC".')
    funding_rate: float = Field(
        ..., description="Raw funding rate fraction (0.0001 = 0.01% per 8h)."
    )
    funding_rate_percent: float = Field(
        ..., description="Funding rate as a percentage (0.01 = 0.01%)."
    )


class CMEGapEntry(BaseModel):
    """A single unfilled CME gap on BTC weekly candles."""

    date: str = Field(..., description='Gap candle date (YYYY-MM-DD).')
    gap_percent: float = Field(..., description="Size of the gap in percent.")
    direction: str = Field(..., description='"up" or "down".')
    filled: bool = Field(..., description="Whether the gap has since been filled.")


class MacroResponse(BaseModel):
    """Shape of the ``GET /api/v1/macro`` response."""

    data: dict[str, Any]
    cached_at: Optional[str] = None
    stale: bool = False
    errors: Optional[list[dict[str, str]]] = None

    model_config = {"json_schema_extra": {"example": {
        "data": {
            "btc_dominance": 52.3,
            "usdt_dominance": 4.21,
            "dxy": 104.5,
            "dxy_error": None,
            "fear_greed_index": 45,
            "fear_greed_label": "Fear",
            "binance_ls_ratio": 1.42,
            "funding_rates": [
                {"symbol": "BTC", "funding_rate": 0.0001, "funding_rate_percent": 0.01},
            ],
            "cme_gaps": [
                {"date": "2026-06-20", "gap_percent": 1.5, "direction": "up", "filled": False},
            ],
            "regime": "mixed",
        },
        "cached_at": "2026-07-05T12:00:00+00:00",
        "stale": False,
        "errors": None,
    }}}


# ── Route ──────────────────────────────────────────────────────────────────


@router.get("/macro", response_model=MacroResponse)
async def get_macro(
    current_user: User = Depends(get_current_user),
) -> MacroResponse:
    """Return macro market data: BTC.D, USDT.D, DXY, Fear & Greed,
    Binance Long/Short ratio, funding rates, CME gaps, and regime detection.

    Data is cached in memory for 15 minutes.  A request triggers an
    asynchronous refresh only when the cached data is older than
    ``CACHE_TTL`` (15 min) — all sources are fetched concurrently.
    Any source that fails returns ``null`` for that field with the
    error listed in ``errors``.  Previous cached values are retained
    on failure, so a single blip never blanks the dashboard.
    """
    if is_stale():
        return MacroResponse(**await refresh_macro_data())
    return MacroResponse(**build_response())
