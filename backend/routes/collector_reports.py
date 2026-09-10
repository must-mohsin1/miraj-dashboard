"""Signed ingestion and authenticated reads for collector public reports."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import CollectorIngestEvent, CollectorIngestFailure, CollectorIngestReplay, CollectorReport, User
from backend.schemas import (
    CollectorLatestReportResponse,
    CollectorReportIngestRequest,
    CollectorReportResponse,
)


router = APIRouter(prefix="/api/v1/collector-reports", tags=["collector-reports"])
MAX_SIGNATURE_AGE_SECONDS = 300
MAX_REPORT_AGE_SECONDS = 900
_SECRET_LIKE_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?:
        api[\s_-]*key
        | access[\s_-]*token
        | auth(?:entication|orization)?
        | bearer[\s_-]*token
        | client[\s_-]*(?:secret|token)
        | credential(?:s)?
        | private[\s_-]*key
        | pass[\s_-]*(?:word|wd)
        | secret(?:[\s_-]*(?:key|token))?
        | token
    )\b
    \s*(?:=|:)\s*\S+
    """
)


def _contains_secret_like_string(value: Any) -> bool:
    """Reject assignment-style credentials without retaining the matched text."""
    if isinstance(value, str):
        return _SECRET_LIKE_ASSIGNMENT.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_secret_like_string(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret_like_string(item) for item in value)
    return False


def _request_signature_payload(timestamp: str, nonce: str, body: bytes) -> bytes:
    return f"{timestamp}.{nonce}.".encode("ascii") + body


def _report_id(symbol: str, generated_at: str, payload_sha256: str) -> str:
    return f"{symbol.lower()}-{generated_at}-{payload_sha256[:32]}"


def _canonical_content_digest(raw_payload: dict[str, Any]) -> str:
    """Hash canonical UTF-8 JSON: sorted keys, compact separators, unescaped Unicode."""
    content = {
        key: value
        for key, value in raw_payload.items()
        if key not in {"report_id", "payload_sha256"}
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


async def _persist_semantic_failure(
    session: AsyncSession, *, nonce: str, request_digest: str, raw_payload: Any
) -> None:
    """Persist only a generic rejection audit and a safe latest-state shell."""
    session.add(CollectorIngestEvent(
        nonce=nonce,
        request_digest=request_digest,
        status="failed",
        validation_error="semantic_payload_invalid",
    ))
    session.add(CollectorIngestFailure(
        nonce=nonce,
        request_digest=request_digest,
        validation_error="semantic_payload_invalid",
    ))
    symbol = raw_payload.get("symbol") if isinstance(raw_payload, dict) else None
    if isinstance(symbol, str) and symbol.strip().isalnum() and len(symbol.strip()) <= 40:
        rejected_report_id = f"rejected-{request_digest}"
        existing = await session.scalar(
            select(CollectorReport).where(CollectorReport.report_id == rejected_report_id)
        )
        if existing is None:
            try:
                async with session.begin_nested():
                    session.add(CollectorReport(
                        report_id=rejected_report_id,
                        symbol=symbol.strip().upper(),
                        generated_at=datetime.utcnow(),
                        report={},
                        payload_digest=request_digest,
                        status="failed",
                        validation_error="semantic_payload_invalid",
                    ))
                    await session.flush()
            except IntegrityError:
                # A concurrent request created the same digest-keyed safe shell.
                pass
    await session.commit()


def _verify_signature(*, timestamp: str | None, nonce: str | None, signature: str | None, body: bytes) -> str:
    secret = os.environ.get("COLLECTOR_INGEST_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Collector ingestion is not configured",
        )
    if not timestamp or not nonce or not signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing collector signature")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid collector timestamp") from exc
    if abs(time.time() - timestamp_value) > MAX_SIGNATURE_AGE_SECONDS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired collector signature")

    expected = hmac.new(
        secret.encode("utf-8"),
        _request_signature_payload(timestamp, nonce, body),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid collector signature")
    return nonce


def _response(report: CollectorReport, *, status_value: str, stale: bool, idempotent: bool | None = None) -> CollectorReportResponse:
    public_report = None
    if status_value != "failed":
        public_report = CollectorReportIngestRequest.model_validate(report.report).model_dump(
            mode="json", by_alias=True, exclude_unset=True, exclude_none=True,
        )
    return CollectorReportResponse(
        status=status_value,
        stale=stale,
        received_at=report.received_at,  # type: ignore[arg-type]
        report=public_report,
        idempotent=idempotent,
    )


@router.post(
    "",
    response_model=CollectorReportResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_collector_report(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CollectorReportResponse:
    """Verify, persist, and deduplicate a signed public collector report."""
    body = await request.body()
    timestamp = request.headers.get("X-Collector-Timestamp")
    nonce = _verify_signature(
        timestamp=timestamp,
        nonce=request.headers.get("X-Collector-Nonce"),
        signature=request.headers.get("X-Collector-Signature"),
        body=body,
    )
    request_digest = hashlib.sha256(body).hexdigest()
    session.add(CollectorIngestReplay(nonce=nonce, request_digest=request_digest))
    session.add(CollectorIngestEvent(nonce=nonce, request_digest=request_digest, status="received"))
    try:
        await session.flush()
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collector request replayed") from exc

    try:
        raw_payload = json.loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        await _persist_semantic_failure(session, nonce=nonce, request_digest=request_digest, raw_payload=None)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid collector report") from exc

    try:
        payload = CollectorReportIngestRequest.model_validate(raw_payload)
    except (TypeError, ValueError):
        await _persist_semantic_failure(session, nonce=nonce, request_digest=request_digest, raw_payload=raw_payload)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid collector report")
    normalized_payload = payload.model_dump(mode="json", by_alias=True, exclude_unset=True)
    if _contains_secret_like_string(normalized_payload):
        await _persist_semantic_failure(session, nonce=nonce, request_digest=request_digest, raw_payload=raw_payload)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid collector report")
    canonical_digest = _canonical_content_digest(raw_payload)
    if not hmac.compare_digest(canonical_digest, payload.payload_sha256):
        await _persist_semantic_failure(session, nonce=nonce, request_digest=request_digest, raw_payload=raw_payload)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Collector payload digest mismatch")
    try:
        expected_report_id = _report_id(payload.symbol, raw_payload["generated_at"], payload.payload_sha256)
    except (KeyError, TypeError):
        await _persist_semantic_failure(session, nonce=nonce, request_digest=request_digest, raw_payload=raw_payload)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid collector report")
    if not hmac.compare_digest(expected_report_id, payload.report_id):
        await _persist_semantic_failure(session, nonce=nonce, request_digest=request_digest, raw_payload=raw_payload)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Collector report ID does not match content")

    existing = await session.scalar(
        select(CollectorReport).where(CollectorReport.report_id == str(payload.report_id))
    )
    if existing is not None:
        if str(existing.payload_digest) != request_digest:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collector report ID already exists")
        return _response(existing, status_value=str(existing.status), stale=False, idempotent=True)

    report = CollectorReport(
        report_id=str(payload.report_id),
        symbol=payload.symbol.upper(),
        generated_at=payload.generated_at,
        report=normalized_payload,
        payload_digest=request_digest,
        status="validated",
        validation_error=None,
    )
    session.add(report)
    await session.flush()
    session.add(CollectorIngestEvent(
        nonce=nonce,
        request_digest=request_digest,
        report_id=str(payload.report_id),
        status="validated",
    ))
    await session.flush()
    return _response(report, status_value="validated", stale=False, idempotent=False)


@router.get("/latest", response_model=CollectorLatestReportResponse)
async def get_latest_collector_report(
    symbol: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CollectorLatestReportResponse:
    """Return the latest durable collector lifecycle state to authenticated users."""
    del current_user
    report = await session.scalar(
        select(CollectorReport)
        .where(CollectorReport.symbol == symbol.strip().upper())
        .order_by(CollectorReport.received_at.desc(), CollectorReport.id.desc())
        .limit(1)
    )
    if report is None:
        return CollectorReportResponse(status="unavailable", stale=True, received_at=None, report=None)
    if str(report.status) == "failed":
        return _response(report, status_value="failed", stale=True)
    generated_at = report.generated_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    age_seconds = time.time() - generated_at.timestamp()
    stale = age_seconds > MAX_REPORT_AGE_SECONDS
    return _response(report, status_value="stale" if stale else str(report.status), stale=stale)
