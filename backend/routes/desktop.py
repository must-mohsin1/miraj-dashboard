"""Authenticated read-only desktop position-intelligence routes."""

from __future__ import annotations

import json
import logging
from datetime import timezone
from typing import Any, Dict, List, Mapping, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import Analysis, User
from backend.routes.portfolio import _get_latest_snapshot, _load_positions, _serialise_position

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/desktop", tags=["desktop"])


def build_desktop_position_intelligence(**kwargs: Any) -> Dict[str, Any]:
    """Delegate to the desktop contract service when the service module is present."""

    from backend.services.desktop_position_service import (  # noqa: PLC0415 - lazy for independent route tests
        build_desktop_position_intelligence as _build_desktop_position_intelligence,
    )

    return _build_desktop_position_intelligence(**kwargs)


@router.get("/position-intelligence")
async def get_desktop_position_intelligence(
    exchange: str = Query(default="mexc"),
    symbol: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """Return schema_version=1 desktop position intelligence from cached data only."""

    exchange_slug = _require_desktop_exchange(exchange)

    try:
        user_id = cast(int, current_user.id)
        positions = await _load_cached_positions(session, user_id, exchange_slug)
        source_times = await _load_source_times(session, user_id, exchange_slug)
        symbols = {str(position.get("symbol") or "").upper() for position in positions if position.get("symbol")}
        if symbol:
            symbols.add(symbol.strip().upper())
        scans = await _load_latest_scans(session, user_id, exchange_slug, symbols)
        return build_desktop_position_intelligence(
            positions=positions,
            exchange=exchange_slug,
            selected_symbol=symbol,
            scans_by_symbol=scans,
            dca_recommendations_by_symbol=_extract_recommendations(scans),
            position_alerts_by_symbol=_extract_alerts(scans),
            portfolio_last_refreshed=source_times.get("portfolio_last_refreshed"),
            mark_price_last_refreshed=source_times.get("mark_price_last_refreshed"),
            mark_price_source="cached_position",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Desktop position-intelligence unavailable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to build desktop position intelligence",
            headers={"X-Error-Code": "desktop_position_intelligence_unavailable"},
        ) from exc


def _require_desktop_exchange(exchange: str) -> str:
    exchange_slug = exchange.strip().lower()
    if exchange_slug != "mexc":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unsupported desktop exchange",
            headers={"X-Error-Code": "unsupported_exchange"},
        )
    return exchange_slug


async def _load_cached_positions(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> List[Dict[str, Any]]:
    rows = await _load_positions(session, user_id, exchange)
    return [_serialise_position(row) for row in rows]


async def _load_source_times(
    session: AsyncSession,
    user_id: int,
    exchange: str,
) -> Dict[str, Any]:
    snapshot = await _get_latest_snapshot(session, user_id, exchange)
    if snapshot is None:
        return {}

    timestamp = snapshot.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return {
        "portfolio_last_refreshed": timestamp,
        "mark_price_last_refreshed": timestamp,
    }


def _parse_json_blob(blob: Optional[str]) -> Dict[str, Any]:
    if not blob:
        return {}
    try:
        parsed = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _analysis_matches_exchange(analysis: Analysis, exchange: str) -> bool:
    params = _parse_json_blob(cast(Optional[str], analysis.parameters))
    result = _parse_json_blob(cast(Optional[str], analysis.result))
    recorded_exchange = params.get("exchange") or result.get("exchange")
    return recorded_exchange is None or str(recorded_exchange).lower() == exchange


async def _load_latest_scans(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbols: set[str],
) -> Dict[str, Dict[str, Any]]:
    query = select(Analysis).where(Analysis.user_id == user_id)
    if symbols:
        query = query.where(Analysis.pair.in_(symbols))
    query = query.order_by(Analysis.created_at.desc())
    result = await session.execute(query)

    scans: Dict[str, Dict[str, Any]] = {}
    for analysis in result.scalars().all():
        pair = cast(str, analysis.pair)
        pair_key = pair.upper()
        if pair_key in scans or not _analysis_matches_exchange(analysis, exchange):
            continue
        parsed = _parse_json_blob(cast(Optional[str], analysis.result))
        if parsed:
            scans[pair_key] = parsed
    return scans


def _extract_recommendations(scans: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    recommendations: Dict[str, Dict[str, Any]] = {}
    for symbol, scan in scans.items():
        dca = scan.get("dca") or scan.get("dca_recommendation")
        if isinstance(dca, dict):
            recommendations[symbol] = dict(dca)
    return recommendations


def _extract_alerts(scans: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    alerts_by_symbol: Dict[str, Dict[str, Any]] = {}
    for symbol, scan in scans.items():
        alerts = scan.get("position_alerts") or scan.get("alerts")
        if isinstance(alerts, dict):
            alerts_by_symbol[symbol] = dict(alerts)
    return alerts_by_symbol
