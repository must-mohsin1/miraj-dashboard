"""MEXC Contract public kline protocol helpers.

The websocket transport is deliberately separate from parsing so malformed or
out-of-order exchange frames cannot turn into market decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

MEXC_CONTRACT_WS_URL = "wss://contract.mexc.com/edge"


@dataclass(frozen=True)
class KlineCandle:
    symbol: str
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def to_mexc_symbol(symbol: str) -> str:
    """Normalize BTCUSDT/BTC_USDT/BTC-USDT to MEXC's BTC_USDT form."""
    compact = symbol.strip().upper().replace("_", "").replace("-", "").replace("/", "")
    if not compact.endswith("USDT") or len(compact) <= 4:
        raise ValueError("only USDT perpetual symbols are supported")
    return f"{compact[:-4]}_USDT"


def from_mexc_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("_", "").replace("-", "").replace("/", "")


def build_kline_subscription(symbol: str, interval: str) -> dict[str, Any]:
    """Return the MEXC public-kline subscription payload."""
    if interval not in {"Min1", "Min5", "Min15", "Min60", "Hour4"}:
        raise ValueError(f"unsupported MEXC interval: {interval}")
    return {"method": "sub.kline", "param": {"symbol": to_mexc_symbol(symbol), "interval": interval}}


def parse_rest_klines(symbol: str, payload: Mapping[str, Any]) -> list[KlineCandle]:
    """Parse MEXC Contract's columnar public REST kline response."""
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return []
    columns = ("time", "open", "high", "low", "close", "vol")
    if any(not isinstance(data.get(column), list) for column in columns):
        return []
    rows: list[KlineCandle] = []
    lengths = [len(data[column]) for column in columns]
    for index in range(min(lengths, default=0)):
        try:
            timestamp = int(data["time"][index])
            rows.append(KlineCandle(
                symbol=from_mexc_symbol(symbol),
                timestamp_ms=timestamp * 1000 if timestamp < 100_000_000_000 else timestamp,
                open=float(data["open"][index]),
                high=float(data["high"][index]),
                low=float(data["low"][index]),
                close=float(data["close"][index]),
                volume=float(data["vol"][index]),
            ))
        except (TypeError, ValueError):
            continue
    return rows


def parse_kline_message(message: Mapping[str, Any]) -> Optional[KlineCandle]:
    """Parse an MEXC ``push.kline`` message, returning ``None`` for other frames."""
    if message.get("channel") != "push.kline":
        return None
    raw = message.get("data")
    symbol = message.get("symbol")
    if not isinstance(raw, Mapping) or not isinstance(symbol, str):
        return None
    try:
        timestamp = int(raw["t"])
        # MEXC currently emits second-resolution kline starts; normalize legacy
        # millisecond frames too so candle replacement is deterministic.
        timestamp_ms = timestamp * 1000 if timestamp < 100_000_000_000 else timestamp
        return KlineCandle(
            symbol=from_mexc_symbol(symbol),
            timestamp_ms=timestamp_ms,
            open=float(raw["o"]),
            high=float(raw["h"]),
            low=float(raw["l"]),
            close=float(raw["c"]),
            volume=float(raw.get("a", raw.get("v", 0))),
        )
    except (KeyError, TypeError, ValueError):
        return None
