"""Static redacted Phase 2B capital-flow fixtures. Synthetic only — never live keys."""

from __future__ import annotations

BASE_MS = 1_786_100_000_000


def funding_row(
    entry_id: str | None = "redacted-fund-001",
    *,
    funding: str = "-1.25",
    currency: str = "USDT",
    offset: int = 0,
) -> dict:
    ts = BASE_MS + offset * 60_000
    row = {
        "symbol": "BTC_USDT",
        "currency": currency,
        "funding": funding,
        "fundingRate": "0.0001",
        "positionValue": "1000",
        "positionType": "1",
        "settleTime": ts,
        "createTime": ts - 1000,
    }
    if entry_id is not None:
        row["id"] = entry_id
    return row


def futures_transfer_row(
    entry_id: str | None = "redacted-xfer-001",
    *,
    amount: str = "50.0",
    transfer_type: str = "IN",
    currency: str = "USDT",
    offset: int = 0,
) -> dict:
    ts = BASE_MS + offset * 60_000
    row = {
        "currency": currency,
        "amount": amount,
        "type": transfer_type,
        "state": "SUCCESS",
        "createTime": ts,
        "updateTime": ts + 500,
    }
    if entry_id is not None:
        row["id"] = entry_id
        row["tranId"] = entry_id
    return row


def deposit_row(
    entry_id: str | None = "redacted-dep-001",
    *,
    amount: float = 100.0,
    currency: str = "USDT",
    offset: int = 0,
) -> dict:
    """ccxt-unified shaped deposit."""
    ts = BASE_MS + offset * 60_000
    row = {
        "currency": currency,
        "amount": amount,
        "status": "ok",
        "timestamp": ts,
        "datetime": None,
        "txid": f"tx-{entry_id}" if entry_id else None,
        "info": {"coin": currency, "amount": str(amount), "status": "5"},
    }
    if entry_id is not None:
        row["id"] = entry_id
    return row


def withdrawal_row(
    entry_id: str | None = "redacted-wd-001",
    *,
    amount: float = 25.0,
    currency: str = "USDT",
    offset: int = 0,
) -> dict:
    ts = BASE_MS + offset * 60_000
    row = {
        "currency": currency,
        "amount": amount,
        "status": "ok",
        "timestamp": ts,
        "txid": f"tx-{entry_id}" if entry_id else None,
        "info": {"coin": currency, "amount": str(amount), "status": "7"},
    }
    if entry_id is not None:
        row["id"] = entry_id
    return row


FUNDING_WITH_ID = funding_row("redacted-fund-001", funding="-1.25", offset=1)
FUNDING_RECEIPT = funding_row("redacted-fund-002", funding="0.55", offset=2)
FUNDING_IDLESS = funding_row(None, funding="-0.10", offset=3)
TRANSFER_IN = futures_transfer_row("redacted-xfer-in", amount="50.0", transfer_type="IN", offset=4)
TRANSFER_OUT = futures_transfer_row("redacted-xfer-out", amount="20.0", transfer_type="OUT", offset=5)
DEPOSIT = deposit_row("redacted-dep-001", amount=100.0, offset=6)
WITHDRAWAL = withdrawal_row("redacted-wd-001", amount=25.0, offset=7)
DEPOSIT_IDLESS = deposit_row(None, amount=11.0, offset=8)
