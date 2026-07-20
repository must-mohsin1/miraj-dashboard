"""Read-only Decision Desk snapshot of watchlist scope and durable signals."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import RealtimeSignal, User, WatchlistPair
from backend.realtime.mexc_contracts import classify_market_scope, fetch_mexc_contract_catalogue
from backend.schemas import DecisionDeskResponse, DecisionDeskSignal, DecisionDeskWatchlistPair

router = APIRouter(prefix="/api/v1/decision-desk", tags=["decision-desk"])


def _missing_gates(value: str | None) -> list[str]:
    """Decode the durable gate list without allowing malformed historical data to fail the snapshot."""
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [gate for gate in decoded if isinstance(gate, str)] if isinstance(decoded, list) else []


@router.get("/now", response_model=DecisionDeskResponse)
async def now(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionDeskResponse:
    """Return the authenticated user's persisted advisory snapshot without inferring a new signal."""
    watchlist_result = await session.execute(
        select(WatchlistPair)
        .where(WatchlistPair.user_id == current_user.id)
        .order_by(WatchlistPair.sort_order.asc())
    )
    signal_result = await session.execute(
        select(RealtimeSignal)
        .where(RealtimeSignal.user_id == current_user.id)
        .order_by(RealtimeSignal.updated_at.desc(), RealtimeSignal.id.desc())
    )
    catalogue = await fetch_mexc_contract_catalogue()

    watchlist = []
    for pair in watchlist_result.scalars():
        market_scope, mexc_symbol = classify_market_scope(pair.pair, catalogue)
        watchlist.append(
            DecisionDeskWatchlistPair(
                pair=pair.pair,
                market_scope=market_scope,
                mexc_symbol=mexc_symbol,
            )
        )

    signals = [
        DecisionDeskSignal(
            pair=signal.pair,
            direction=signal.direction,
            state=signal.state,
            missing_gates=_missing_gates(signal.missing_gates),
            created_at=signal.created_at,
            updated_at=signal.updated_at,
        )
        for signal in signal_result.scalars()
    ]
    return DecisionDeskResponse(generated_at=datetime.utcnow(), watchlist=watchlist, signals=signals)
