"""Static redacted Phase 2A MEXC sync fixtures.

All values are synthetic and safe for local mocked tests only. Do not replace
these with private exchange payloads.
"""

from __future__ import annotations

BASE_MS = 1_786_000_000_000


def history_position(position_id: str, *, offset: int = 0, pnl: str = "1.25", symbol: str = "BTC_USDT") -> dict:
    ts = BASE_MS + offset * 60_000
    return {
        "positionId": position_id,
        "symbol": symbol,
        "positionType": "1",
        "closeVol": "1",
        "holdAvgPrice": "100.0",
        "closeAvgPrice": "101.0",
        "closeProfitLoss": pnl,
        "profitRatio": "0.0125",
        "leverage": "5",
        "createTime": ts - 30_000,
        "updateTime": ts,
        "state": "3",
    }


def history_order(order_id: str, *, offset: int = 0, price: str = "100.0", symbol: str = "BTC_USDT") -> dict:
    ts = BASE_MS + offset * 60_000
    return {
        "orderId": order_id,
        "symbol": symbol,
        "side": "1",
        "orderType": "1",
        "state": "3",
        "openType": "1",
        "price": price,
        "vol": "1",
        "dealVol": "1",
        "dealAvgPrice": price,
        "fee": "0.01",
        "feeCurrency": "USDT",
        "leverage": "5",
        "createTime": ts,
        "updateTime": ts + 1_000,
    }


def paged_rows(rows: list[dict], page_size: int = 100) -> list[list[dict]]:
    return [rows[i : i + page_size] for i in range(0, len(rows), page_size)]


POSITION_HISTORY_237 = [
    history_position(f"redacted-pos-{idx:03d}", offset=idx) for idx in range(237)
]

ORDER_HISTORY_225 = [
    history_order(f"redacted-order-{idx:03d}", offset=idx) for idx in range(225)
]

PARTIAL_CLOSE_DUPLICATES = [
    history_position("partial-close-a", offset=999, pnl="1.11", symbol="ETH_USDT"),
    history_position("partial-close-b", offset=999, pnl="2.22", symbol="ETH_USDT"),
]

MUTATED_POSITION = history_position("partial-close-a", offset=999, pnl="9.99", symbol="ETH_USDT")
MUTATED_ORDER = history_order("same-order-id", offset=999, price="123.45", symbol="ETH_USDT")

FUTURES_ACCOUNT_ASSETS = {
    "success": True,
    "data": [
        {
            "currency": "USDT",
            "equity": "1234.56",
            "availableBalance": "1000.25",
            "frozenBalance": "10.0",
            "cashBalance": "1111.11",
            "positionMargin": "88.8",
            "unrealized": "12.34",
            "bonus": "0",
            "availableCash": "999.99",
            "debtAmount": "0",
            "updateTime": BASE_MS + 5_000,
        }
    ],
}

MEXC_510_REDACTED_ERROR = {
    "success": False,
    "code": 510,
    "message": "rate limited for REDACTED synthetic-key value",
}
