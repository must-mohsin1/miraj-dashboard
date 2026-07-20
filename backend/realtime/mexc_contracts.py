"""Validated MEXC Contract market metadata.

A symbol is eligible for real-time monitoring only when it is present in the
public MEXC Contract catalogue. Syntactic USDT normalization alone is never
sufficient evidence that a contract exists.
"""

from __future__ import annotations

import time
from collections.abc import Collection
from typing import Any

from backend.realtime.mexc_stream import from_mexc_symbol, to_mexc_symbol

MEXC_CONTRACT_DETAIL_URL = "https://contract.mexc.com/api/v1/contract/detail"
_DEFAULT_CATALOGUE_TTL_SECONDS = 300.0
_catalogue_cache: tuple[float, frozenset[str]] | None = None


def reset_mexc_contract_catalogue_cache() -> None:
    """Clear process-local catalogue state (primarily for deterministic tests)."""
    global _catalogue_cache
    _catalogue_cache = None


async def fetch_mexc_contract_catalogue(
    client: Any | None = None, *, ttl_seconds: float = _DEFAULT_CATALOGUE_TTL_SECONDS
) -> frozenset[str] | None:
    """Fetch MEXC Contract symbols with a bounded process-local TTL cache.

    The catalogue is public metadata. Any network or payload failure returns
    ``None`` so callers fail closed and retain symbols as research-only.
    """
    global _catalogue_cache
    now = time.monotonic()
    if _catalogue_cache is not None and now - _catalogue_cache[0] < max(0.0, ttl_seconds):
        return _catalogue_cache[1]

    try:
        if client is None:
            import httpx
            async with httpx.AsyncClient(timeout=10) as owned_client:
                response = await owned_client.get(MEXC_CONTRACT_DETAIL_URL)
        else:
            response = await client.get(MEXC_CONTRACT_DETAIL_URL)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return None
        symbols = frozenset(
            item["symbol"].strip().upper()
            for item in rows
            if isinstance(item, dict) and isinstance(item.get("symbol"), str)
        )
    except Exception:
        return None

    _catalogue_cache = (now, symbols)
    return symbols


def classify_market_scope(symbol: str, catalogue: Collection[str] | None) -> tuple[str, str | None]:
    """Classify *symbol* against an explicitly supplied MEXC contract catalogue.

    ``catalogue=None`` denotes unavailable metadata and is intentionally
    fail-closed: unknown exchange availability is research-only.
    """
    if catalogue is None:
        return "research_only", None

    normalized = symbol.strip().upper().replace("_", "").replace("-", "").replace("/", "")
    if normalized.endswith("USD") and not normalized.endswith("USDT"):
        normalized = f"{normalized}T"
    try:
        contract_symbol = to_mexc_symbol(normalized)
    except ValueError:
        return "research_only", None

    if contract_symbol not in catalogue:
        return "research_only", None
    return "mexc_realtime", from_mexc_symbol(contract_symbol)
