"""Normalized public candle stream adapters for chart consumers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from backend.realtime.mexc_stream import parse_kline_message


_BINANCE_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d", "1w"}
_MEXC_INTERVALS = {"1m": "Min1", "5m": "Min5", "15m": "Min15", "1h": "Min60", "4h": "Hour4"}


@dataclass(frozen=True)
class NormalizedCandle:
    symbol: str
    timeframe: str
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_symbol(symbol: str) -> str:
    """Return compact uppercase symbol for public USDT market streams."""
    return symbol.strip().upper().replace("/", "").replace("-", "").replace("_", "")


def binance_stream_url(symbol: str, timeframe: str) -> str:
    compact = normalize_symbol(symbol)
    if not compact.endswith("USDT"):
        raise ValueError("Binance chart stream requires a USDT symbol")
    if timeframe not in _BINANCE_INTERVALS:
        raise ValueError(f"unsupported Binance timeframe: {timeframe}")
    return f"wss://stream.binance.com:9443/ws/{compact.lower()}@kline_{timeframe}"


def mexc_subscription(symbol: str, timeframe: str) -> dict[str, Any]:
    from backend.realtime.mexc_stream import build_kline_subscription

    interval = _MEXC_INTERVALS.get(timeframe)
    if interval is None:
        raise ValueError(f"unsupported MEXC timeframe: {timeframe}")
    return build_kline_subscription(symbol, interval)


def parse_binance_message(message: Mapping[str, Any], timeframe: str) -> NormalizedCandle | None:
    kline = message.get("k")
    if message.get("e") != "kline" or not isinstance(kline, Mapping):
        return None
    try:
        return NormalizedCandle(
            symbol=normalize_symbol(str(kline["s"])),
            timeframe=timeframe,
            time=int(kline["t"]) // 1000,
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            closed=bool(kline["x"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def parse_mexc_message(message: Mapping[str, Any], timeframe: str) -> NormalizedCandle | None:
    parsed = parse_kline_message(message)
    if parsed is None:
        return None
    return NormalizedCandle(
        symbol=normalize_symbol(parsed.symbol),
        timeframe=timeframe,
        time=parsed.timestamp_ms // 1000,
        open=parsed.open,
        high=parsed.high,
        low=parsed.low,
        close=parsed.close,
        volume=parsed.volume,
        # MEXC push.kline does not expose a close flag; consumers must use
        # timestamp rollover for boundary detection.
        closed=False,
    )


def sse_event(event: str, payload: Mapping[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
