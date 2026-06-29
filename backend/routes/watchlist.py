"""Watchlist routes — CRUD for user watchlist pairs + batch parallel scan.

Endpoints
---------
POST   /api/v1/watchlist              — add a trading pair to the current user's watchlist
GET    /api/v1/watchlist              — list all watchlist pairs for the current user
DELETE /api/v1/watchlist/{pair_id}     — remove a pair from the watchlist by database id
PUT    /api/v1/watchlist/reorder       — reorder the current user's watchlist pairs by id
POST   /api/v1/scan/batch             — run the full pipeline on all active watchlist pairs
                                         in parallel, sorted by confluence_score desc.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import User, WatchlistPair
from backend.schemas import (
    WatchlistListResponse,
    WatchlistPairCreateRequest,
    WatchlistPairWithScore,
    WatchlistReorderRequest,
)
from backend.services.batch_scanner import (
    can_run_batch,
    clear_rate_limit,
    mark_batch_run,
    run_batch_scan,
    seconds_until_retry,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["watchlist"])


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _get_next_sort_order(
    user_id: int, session: AsyncSession
) -> int:
    """Return the next available sort_order for a new watchlist pair."""
    result = await session.execute(
        select(WatchlistPair.sort_order)
        .where(WatchlistPair.user_id == user_id)
        .order_by(WatchlistPair.sort_order.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return (row + 1) if row is not None else 0


def _enrich_pair(pair: WatchlistPair) -> WatchlistPairWithScore:
    """Convert an ORM WatchlistPair to the enriched response model."""
    return WatchlistPairWithScore(
        id=pair.id,
        user_id=pair.user_id,
        pair=pair.pair,
        sort_order=pair.sort_order,
        created_at=pair.created_at,
        score=None,
        status="Active",
    )


# ── CRUD endpoints ──────────────────────────────────────────────────────────


@router.post(
    "/watchlist",
    response_model=WatchlistPairWithScore,
    status_code=status.HTTP_201_CREATED,
)
async def add_watchlist_pair(
    body: WatchlistPairCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchlistPairWithScore:
    """Add a trading pair to the current user's watchlist.

    Returns 409 Conflict when the pair is already in the watchlist.
    """
    symbol = body.pair.strip().upper()

    # Check for duplicate
    existing_result = await session.execute(
        select(WatchlistPair).where(
            WatchlistPair.user_id == current_user.id,
            WatchlistPair.pair == symbol,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Symbol '{symbol}' is already in your watchlist",
        )

    next_order = await _get_next_sort_order(current_user.id, session)
    pair = WatchlistPair(
        user_id=current_user.id,
        pair=symbol,
        sort_order=next_order,
    )
    session.add(pair)
    await session.flush()
    await session.refresh(pair)
    return _enrich_pair(pair)


@router.get(
    "/watchlist",
    response_model=WatchlistListResponse,
)
async def list_watchlist(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchlistListResponse:
    """Return all watchlist pairs for the current user, ordered by sort_order."""
    result = await session.execute(
        select(WatchlistPair)
        .where(WatchlistPair.user_id == current_user.id)
        .order_by(WatchlistPair.sort_order.asc())
    )
    rows = list(result.scalars().all())
    enriched = [_enrich_pair(p) for p in rows]
    return WatchlistListResponse(total=len(enriched), pairs=enriched)


@router.delete(
    "/watchlist/{pair_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_watchlist_pair(
    pair_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove a trading pair from the current user's watchlist by database id.

    Returns 404 when the pair does not exist or does not belong to the user.
    """
    result = await session.execute(
        select(WatchlistPair).where(
            WatchlistPair.id == pair_id,
            WatchlistPair.user_id == current_user.id,
        )
    )
    pair = result.scalar_one_or_none()
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist pair with id {pair_id} not found",
        )

    await session.delete(pair)


@router.put(
    "/watchlist/reorder",
    status_code=status.HTTP_200_OK,
)
async def reorder_watchlist(
    body: WatchlistReorderRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Reorder the current user's watchlist pairs by database id.

    Expects a JSON body:
        {"pair_ids": [3, 1, 2]}

    All provided pair_ids must belong to the current user.
    Returns the number of rows updated.
    """
    # Fetch all watchlist pairs for this user to validate ownership
    result = await session.execute(
        select(WatchlistPair.id).where(
            WatchlistPair.user_id == current_user.id,
        )
    )
    owned_ids = {row[0] for row in result.all()}

    # Validate all provided IDs belong to this user
    invalid = [pid for pid in body.pair_ids if pid not in owned_ids]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid pair_ids (not owned by user): {invalid}",
        )

    # Update sort_order for each pair in the request
    reordered = 0
    for idx, pid in enumerate(body.pair_ids):
        result = await session.execute(
            update(WatchlistPair)
            .where(WatchlistPair.id == pid)
            .values(sort_order=idx)
        )
        reordered += result.rowcount

    return {"reordered": reordered}


# ── Batch scan endpoint ──────────────────────────────────────────────────────


@router.post(
    "/scan/batch",
)
async def batch_scan(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Run the full pipeline on all active watchlist pairs in parallel.

    Rate-limited: at most one batch scan per user every 5 minutes.
    Returns results sorted by ``confluence_score`` descending.
    """
    # ── Rate limit check ─────────────────────────────────────────────
    if not can_run_batch(current_user.id):
        retry_after = seconds_until_retry(current_user.id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Batch scan rate limit exceeded. "
                f"Try again in {retry_after} seconds."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    # ── Fetch all active pairs for this user ──────────────────────────
    result = await session.execute(
        select(WatchlistPair)
        .where(WatchlistPair.user_id == current_user.id)
        .order_by(WatchlistPair.sort_order.asc())
    )
    pairs = list(result.scalars().all())

    if not pairs:
        return {"results": [], "total": 0, "succeeded": 0, "failed": 0}

    symbols = [p.pair for p in pairs]

    # ── Run batch scan ────────────────────────────────────────────────
    mark_batch_run(current_user.id)

    try:
        scan_results = await asyncio.to_thread(run_batch_scan, symbols)
    except Exception as exc:
        logger.exception("Batch scan failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Batch scan service error: {exc}",
        ) from exc

    return {
        "results": [
            {**r, "success": "error" not in r}
            for r in scan_results
        ],
        "total": len(scan_results),
        "succeeded": sum(1 for r in scan_results if "error" not in r),
        "failed": sum(1 for r in scan_results if "error" in r),
    }
