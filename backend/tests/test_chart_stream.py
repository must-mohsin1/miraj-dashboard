from backend.realtime.chart_stream import (
    binance_stream_url,
    mexc_subscription,
    normalize_symbol,
    parse_binance_message,
    parse_mexc_message,
)


def test_binance_kline_normalizes_closed_candle():
    candle = parse_binance_message(
        {
            "e": "kline",
            "k": {"s": "SOLUSDT", "t": 1_700_000_000_000, "o": "100", "h": "102", "l": "99", "c": "101", "v": "12.5", "x": True},
        },
        "15m",
    )
    assert candle is not None
    assert candle.symbol == "SOLUSDT"
    assert candle.time == 1_700_000_000
    assert candle.closed is True
    assert candle.volume == 12.5


def test_mexc_kline_normalizes_symbol_and_timestamp():
    candle = parse_mexc_message(
        {"channel": "push.kline", "symbol": "SOL_USDT", "data": {"t": 1_700_000_000, "o": "100", "h": "102", "l": "99", "c": "101", "a": "12.5"}},
        "1h",
    )
    assert candle is not None
    assert candle.symbol == "SOLUSDT"
    assert candle.time == 1_700_000_000
    assert candle.closed is False


def test_stream_protocol_rejects_non_usdt_binance_and_maps_mexc_interval():
    assert normalize_symbol("sol/usdt") == "SOLUSDT"
    assert binance_stream_url("SOLUSDT", "1m").endswith("solusdt@kline_1m")
    assert mexc_subscription("SOLUSDT", "4h")["param"]["interval"] == "Hour4"
