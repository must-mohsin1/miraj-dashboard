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
    summary="List all journal entries (optionally filtered by symbol)",
)
async def list_journal_entries(
    symbol: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JournalEntryListResponse:
    """Return all journal entries for the current user, most recent first.

    An optional ``?symbol=BTCUSDT`` query parameter filters entries to a
    single trading pair (case-insensitive, exact match after upper-casing).
    """
    stmt = select(TradeJournalEntry).where(
        TradeJournalEntry.user_id == current_user.id
    )
    if symbol:
        stmt = stmt.where(TradeJournalEntry.symbol == symbol.upper().strip())

    stmt = stmt.order_by(TradeJournalEntry.created_at.desc())
    result = await session.execute(stmt)
    entries = list(result.scalars().all())

    return JournalEntryListResponse(
        total=len(entries),
        entries=[JournalEntryResponse(**_serialise_entry(e)) for e in entries],
    )


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
    position_id) is copied verbatim so the journal entry remains a stable
    snapshot even if the linked PositionHistory row is later deleted.
    """
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

    entry = TradeJournalEntry(
        user_id=current_user.id,
        exchange=exchange_norm,
        symbol=symbol,
        position_id=body.position_id,
        notes=body.notes,
        tags=tags_norm,
        lessons=body.lessons,
        entry_price=body.entry_price,
        exit_price=body.exit_price,
        pnl=body.pnl,
    )
    session.add(entry)
    await session.flush()  # Populate entry.id
    return JournalEntryResponse(**_serialise_entry(entry))


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
