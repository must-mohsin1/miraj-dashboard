"""Journal routes — trading journal CRUD + screenshot uploads.

Endpoints
---------
GET    /api/v1/journal                  — list all entries (optional ?symbol=X filter)
GET    /api/v1/journal/{id}              — single entry
POST   /api/v1/journal                   — create entry
PUT    /api/v1/journal/{id}              — update entry (notes, tags, lessons)
DELETE /api/v1/journal/{id}              — delete entry
POST   /api/v1/journal/{id}/screenshot   — upload screenshot (multipart form)
GET    /api/v1/journal/{id}/screenshots  — list screenshots for an entry

All endpoints require JWT auth (``Depends(get_current_user)``).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import TradeJournalEntry, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])

# Directory for persisted screenshots. Created on demand at upload time.
SCREENSHOTS_DIR = os.environ.get("JOURNAL_SCREENSHOTS_DIR", "/app/data/screenshots")

# Max upload size: 5 MB per screenshot.
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
}


# ── Pydantic schemas ────────────────────────────────────────────────────────


class JournalEntryCreate(BaseModel):
    """Body for POST /api/v1/journal — create a new journal entry."""

    symbol: str = Field(..., min_length=1, description="Trading pair, e.g. 'BTCUSDT'")
    exchange: Optional[str] = Field(None, description="Exchange slug (e.g. 'mexc')")
    position_id: Optional[int] = Field(None, description="Optional FK to a PositionHistory row")
    notes: Optional[str] = Field(None, description="Free-text trade notes")
    tags: Optional[str] = Field(
        None, description="Comma-separated tags, e.g. 'scalp,swing,breakout'"
    )
    lessons: Optional[str] = Field(None, description="Lessons learned / post-mortem notes")
    entry_price: Optional[float] = Field(None, description="Trade entry price (copied for quick reference)")
    exit_price: Optional[float] = Field(None, description="Trade exit price (copied for quick reference)")
    pnl: Optional[float] = Field(None, description="Realised PnL for the trade (copied for quick reference)")


class JournalEntryUpdate(BaseModel):
    """Body for PUT /api/v1/journal/{id} — update an existing entry."""

    notes: Optional[str] = None
    tags: Optional[str] = None
    lessons: Optional[str] = None


class JournalEntryResponse(BaseModel):
    """Single journal entry as returned by GET/POST/PUT endpoints."""

    id: int
    user_id: int
    exchange: Optional[str] = None
    symbol: str
    position_id: Optional[int] = None
    notes: Optional[str] = None
    tags: Optional[str] = None
    lessons: Optional[str] = None
    screenshots: List[str] = []
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    created_at: str
    updated_at: str


class JournalEntryListResponse(BaseModel):
    """Response envelope for GET /api/v1/journal."""

    total: int
    entries: List[JournalEntryResponse]


class ScreenshotListResponse(BaseModel):
    """Response for GET /api/v1/journal/{id}/screenshots."""

    entry_id: int
    screenshots: List[str]


class ScreenshotUploadResponse(BaseModel):
    """Response for POST /api/v1/journal/{id}/screenshot."""

    entry_id: int
    filename: str
    path: str


# ── Serialiser ───────────────────────────────────────────────────────────────


def _iso_ts(ts: datetime) -> str:
    """Return an ISO-8601 timestamp string (UTC)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _parse_screenshots(raw: Any) -> List[str]:
    """Normalise the screenshots column to a list of strings."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if isinstance(x, str)]
    # SQLite may store JSON as a string in some configurations.
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if isinstance(x, str)]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _serialise_entry(e: TradeJournalEntry) -> Dict[str, Any]:
    """Convert a TradeJournalEntry ORM row to a plain dict for the response model."""
    return {
        "id": e.id,
        "user_id": e.user_id,
        "exchange": e.exchange,
        "symbol": e.symbol,
        "position_id": e.position_id,
        "notes": e.notes,
        "tags": e.tags,
        "lessons": e.lessons,
        "screenshots": _parse_screenshots(e.screenshots),
        "entry_price": e.entry_price,
        "exit_price": e.exit_price,
        "pnl": e.pnl,
        "created_at": _iso_ts(e.created_at),
        "updated_at": _iso_ts(e.updated_at),
    }


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=JournalEntryListResponse,
    summary="List journal entries (filter by symbol, exchange, or tag)",
)
async def list_journal_entries(
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
    tag: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JournalEntryListResponse:
    """Return journal entries for the current user, most recent first.

    Filters (all optional, AND-combined):
    - ``symbol`` — exact match after upper-casing
    - ``exchange`` — exact match after lower-casing
    - ``tag`` — case-insensitive match against comma-separated tags;
      use ``untagged`` for entries with no tags
    """
    stmt = select(TradeJournalEntry).where(
        TradeJournalEntry.user_id == current_user.id
    )
    if symbol:
        stmt = stmt.where(TradeJournalEntry.symbol == symbol.upper().strip())
    if exchange:
        stmt = stmt.where(TradeJournalEntry.exchange == exchange.lower().strip())

    stmt = stmt.order_by(TradeJournalEntry.created_at.desc())
    result = await session.execute(stmt)
    entries = list(result.scalars().all())

    if tag is not None and str(tag).strip() != "":
        entries = _filter_entries_by_tag(entries, str(tag).strip())

    return JournalEntryListResponse(
        total=len(entries),
        entries=[JournalEntryResponse(**_serialise_entry(e)) for e in entries],
    )


def _filter_entries_by_tag(entries: list, tag: str) -> list:
    """Filter journal rows by a single tag token (or the special 'untagged')."""
    needle = tag.strip().lower()
    if needle == "untagged":
        return [e for e in entries if not (e.tags and str(e.tags).strip())]
    out = []
    for e in entries:
        if not e.tags:
            continue
        parts = [p.strip().lower() for p in str(e.tags).split(",") if p.strip()]
        if needle in parts:
            out.append(e)
    return out


@router.get(
    "/{entry_id}",
    response_model=JournalEntryResponse,
    summary="Fetch a single journal entry",
)
async def get_journal_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JournalEntryResponse:
    """Return a single journal entry by ID (owned by the current user)."""
    result = await session.execute(
        select(TradeJournalEntry).where(
            TradeJournalEntry.id == entry_id,
            TradeJournalEntry.user_id == current_user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id} not found",
        )
    return JournalEntryResponse(**_serialise_entry(entry))


@router.post(
    "",
    response_model=JournalEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a journal entry",
)
async def create_journal_entry(
    body: JournalEntryCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JournalEntryResponse:
    """Create a new trading journal entry.

    Optional trade metadata (entry_price, exit_price, pnl, exchange,
    position_id) is copied so the journal entry remains a stable snapshot
    even if the linked PositionHistory row is later deleted.

    When ``position_id`` is omitted, Miraj auto-links the most recent
    unlinked closed position matching symbol (+ exchange when set) and
    fills missing price/PnL fields from that row.

    When tags are omitted/empty and a closed position is linked (explicitly
    or via auto-link), tags are suggested from the position side
    (``long``/``short``) plus pre-entry scan signals when a scan exists
    (``scan_long``/``scan_short``, ``scan_aligned``/``scan_conflict``).
    User-supplied tags are never overwritten.
    """
    from backend.models import PositionHistory

    # Normalise the symbol to upper-case.
    symbol = body.symbol.strip().upper()
    if not symbol:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="symbol must not be empty",
        )

    # Normalise whitespace in tags — collapse internal whitespace so tags display cleanly.
    tags_norm = None
    if body.tags:
        parts = [t.strip() for t in body.tags.split(",") if t.strip()]
        if parts:
            tags_norm = ",".join(parts)

    exchange_norm = body.exchange.strip().lower() if body.exchange else None
    position_id = body.position_id
    entry_price = body.entry_price
    exit_price = body.exit_price
    pnl = body.pnl
    pos = None

    if position_id is not None:
        pos = await session.scalar(
            select(PositionHistory).where(
                PositionHistory.id == position_id,
                PositionHistory.user_id == current_user.id,
            )
        )
        if pos is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"position_id {position_id} not found for this user",
            )
        if entry_price is None:
            entry_price = pos.entry_price
        if exit_price is None:
            exit_price = pos.exit_price
        if pnl is None:
            pnl = pos.pnl
        if exchange_norm is None and pos.exchange:
            exchange_norm = pos.exchange
    else:
        pos = await _auto_link_closed_position(
            session,
            user_id=current_user.id,
            symbol=symbol,
            exchange=exchange_norm,
        )
        if pos is not None:
            position_id = pos.id
            if entry_price is None:
                entry_price = pos.entry_price
            if exit_price is None:
                exit_price = pos.exit_price
            if pnl is None:
                pnl = pos.pnl
            if exchange_norm is None and pos.exchange:
                exchange_norm = pos.exchange

    # Suggest tags from position side + pre-entry scan when the client sent none.
    if tags_norm is None and pos is not None:
        tags_norm = await _suggest_tags_from_position_and_scan(
            session,
            user_id=current_user.id,
            position=pos,
        )

    entry = TradeJournalEntry(
        user_id=current_user.id,
        exchange=exchange_norm,
        symbol=symbol,
        position_id=position_id,
        notes=body.notes,
        tags=tags_norm,
        lessons=body.lessons,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
    )
    session.add(entry)
    await session.flush()  # Populate entry.id
    return JournalEntryResponse(**_serialise_entry(entry))


async def _auto_link_closed_position(
    session: AsyncSession,
    *,
    user_id: int,
    symbol: str,
    exchange: Optional[str],
):
    """Pick the newest unlinked closed position for symbol (+ exchange)."""
    from backend.models import PositionHistory

    already = await session.execute(
        select(TradeJournalEntry.position_id).where(
            TradeJournalEntry.user_id == user_id,
            TradeJournalEntry.position_id.is_not(None),
        )
    )
    used_ids = {row[0] for row in already.all() if row[0] is not None}

    stmt = (
        select(PositionHistory)
        .where(
            PositionHistory.user_id == user_id,
            PositionHistory.symbol == symbol,
        )
        .order_by(
            PositionHistory.close_time.desc().nullslast(),
            PositionHistory.id.desc(),
        )
    )
    if exchange:
        stmt = stmt.where(PositionHistory.exchange == exchange)

    result = await session.execute(stmt)
    for pos in result.scalars().all():
        if pos.id not in used_ids:
            return pos
    return None


async def _suggest_tags_from_position_and_scan(
    session: AsyncSession,
    *,
    user_id: int,
    position,
) -> Optional[str]:
    """Build comma-separated suggested tags from side + nearest pre-entry scan.

    Never invents direction tags without source data. Scan tags are best-effort
    (missing analyses simply omit scan_* tokens).
    """
    parts: List[str] = []
    side = str(getattr(position, "side", None) or "").strip().lower()
    if side in ("long", "short"):
        parts.append(side)

    try:
        from backend.models import Analysis
        from backend.services.position_alert_service import normalize_to_scan_symbol
        from backend.services.scan_attribution_service import (
            _extract_direction,
            _find_nearest_scan_before,
            _parse_result,
        )

        scan_symbol = normalize_to_scan_symbol(position.symbol)
        an_result = await session.execute(
            select(Analysis)
            .where(
                Analysis.user_id == user_id,
                Analysis.pair == scan_symbol,
                Analysis.analysis_type == "scan",
            )
            .order_by(Analysis.created_at.asc())
        )
        scans = list(an_result.scalars().all())
        linked = _find_nearest_scan_before(scans, getattr(position, "open_time", None))
        if linked is not None:
            parsed = _parse_result(linked.result)
            direction = _extract_direction(parsed)
            if direction in ("LONG", "SHORT"):
                scan_tag = f"scan_{direction.lower()}"
                if scan_tag not in parts:
                    parts.append(scan_tag)
                if side in ("long", "short"):
                    if side == direction.lower():
                        parts.append("scan_aligned")
                    else:
                        parts.append("scan_conflict")
            score = parsed.get("confluence_score")
            try:
                score_f = float(score) if score is not None else None
            except (TypeError, ValueError):
                score_f = None
            if score_f is not None and score_f >= 20:
                parts.append("scan_high")
    except Exception:  # pragma: no cover - never block journal create on scan lookup
        logger.exception("scan tag suggestion failed for position %s", getattr(position, "id", None))

    return ",".join(parts) if parts else None


@router.put(
    "/{entry_id}",
    response_model=JournalEntryResponse,
    summary="Update a journal entry",
)
async def update_journal_entry(
    entry_id: int,
    body: JournalEntryUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JournalEntryResponse:
    """Update an existing journal entry's notes, tags, and lessons.

    Only fields provided in the body are changed; omitted fields are left
    untouched.
    """
    result = await session.execute(
        select(TradeJournalEntry).where(
            TradeJournalEntry.id == entry_id,
            TradeJournalEntry.user_id == current_user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id} not found",
        )

    if body.notes is not None:
        entry.notes = body.notes
    if body.tags is not None:
        parts = [t.strip() for t in body.tags.split(",") if t.strip()]
        entry.tags = ",".join(parts) if parts else None
    if body.lessons is not None:
        entry.lessons = body.lessons
    entry.updated_at = datetime.utcnow()
    await session.flush()
    return JournalEntryResponse(**_serialise_entry(entry))


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a journal entry",
)
async def delete_journal_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a journal entry and (best-effort) its screenshot files."""
    result = await session.execute(
        select(TradeJournalEntry).where(
            TradeJournalEntry.id == entry_id,
            TradeJournalEntry.user_id == current_user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id} not found",
        )

    # Best-effort screenshot file cleanup — never block deletion on file errors.
    for path in _parse_screenshots(entry.screenshots):
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            logger.warning("Could not remove screenshot %s: %s", path, exc)

    await session.delete(entry)


@router.post(
    "/{entry_id}/screenshot",
    response_model=ScreenshotUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a screenshot to a journal entry",
)
async def upload_screenshot(
    entry_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ScreenshotUploadResponse:
    """Upload a screenshot image to a journal entry.

    Accepted formats: PNG, JPEG, WebP, GIF. Max size: 5 MB.
    Saved to ``SCREENSHOTS_DIR`` (default ``/app/data/screenshots``).
    """
    result = await session.execute(
        select(TradeJournalEntry).where(
            TradeJournalEntry.id == entry_id,
            TradeJournalEntry.user_id == current_user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id} not found",
        )

    # Validate content type.
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{content_type}'. "
                f"Allowed: {sorted(ALLOWED_IMAGE_TYPES)}"
            ),
        )

    # Read + validate size (UploadFile is a streaming interface; read once).
    contents = await file.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )
    if len(contents) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File too large ({len(contents)} bytes). "
                f"Max: {MAX_SCREENSHOT_BYTES} bytes"
            ),
        )

    # Derive file extension from content type.
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    ext = ext_map.get(content_type, ".png")

    # Ensure the screenshots directory exists.
    try:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create screenshots directory: {exc}",
        ) from exc

    # Save the file with a unique name.
    filename = f"entry_{entry.id}_{uuid.uuid4().hex[:12]}{ext}"
    path = os.path.join(SCREENSHOTS_DIR, filename)
    try:
        with open(path, "wb") as out:
            out.write(contents)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save screenshot: {exc}",
        ) from exc

    # Append path to the entry's screenshots JSON array.
    screenshots = _parse_screenshots(entry.screenshots)
    screenshots.append(path)
    entry.screenshots = screenshots
    entry.updated_at = datetime.utcnow()
    await session.flush()

    return ScreenshotUploadResponse(
        entry_id=entry.id,
        filename=filename,
        path=path,
    )


@router.get(
    "/{entry_id}/screenshots",
    response_model=ScreenshotListResponse,
    summary="List screenshots for a journal entry",
)
async def list_screenshots(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ScreenshotListResponse:
    """Return the list of screenshot file paths attached to an entry."""
    result = await session.execute(
        select(TradeJournalEntry).where(
            TradeJournalEntry.id == entry_id,
            TradeJournalEntry.user_id == current_user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id} not found",
        )
    return ScreenshotListResponse(
        entry_id=entry.id,
        screenshots=_parse_screenshots(entry.screenshots),
    )
