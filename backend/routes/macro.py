"""Macro data route — returns cached macro market data points."""

from fastapi import APIRouter, Depends

from backend.auth import get_current_user
from backend.models import User
from backend.services.macro_service import build_response, is_stale, refresh_macro_data

router = APIRouter(prefix="/api/v1", tags=["macro"])


@router.get("/macro")
async def get_macro(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return macro market data: BTC.D, USDT.D, DXY, Fear & Greed,
    Binance Long/Short ratio, and regime detection.

    Data is cached in memory for 15 minutes.  A request triggers an
    asynchronous refresh only when the cached data is older than
    ``CACHE_TTL`` (15 min) — all 6 sources are fetched concurrently.
    Any source that fails returns ``null`` for that field with the
    error listed in ``errors``.  Previous cached values are retained
    on failure, so a single blip never blanks the dashboard.
    """
    if is_stale():
        return await refresh_macro_data()
    return build_response()
