"""Behaviour tests for the real-time MEXC monitoring primitives."""

from backend.realtime.lifecycle import Confirmation, SignalLifecycle, SignalState
from backend.realtime.mexc_stream import build_kline_subscription, parse_kline_message


def test_confirmation_requires_every_required_gate_before_actionable():
    lifecycle = SignalLifecycle()

    ready = lifecycle.evaluate(
        Confirmation(
            symbol="SOLUSDT",
            direction="LONG",
            higher_timeframe_aligned=True,
            in_entry_zone=True,
            retest_confirmed=True,
            five_minute_confirmed=True,
            fifteen_minute_qqe_confirmed=False,
            volume_confirmed=True,
            data_fresh=True,
        )
    )
    actionable = lifecycle.evaluate(
        Confirmation(
            symbol="SOLUSDT",
            direction="LONG",
            higher_timeframe_aligned=True,
            in_entry_zone=True,
            retest_confirmed=True,
            five_minute_confirmed=True,
            fifteen_minute_qqe_confirmed=True,
            volume_confirmed=True,
            data_fresh=True,
        )
    )

    assert ready.state is SignalState.READY
    assert ready.actionable is False
    assert actionable.state is SignalState.ACTIONABLE
    assert actionable.actionable is True
    assert actionable.dedup_key == "SOLUSDT:LONG:ACTIONABLE"


def test_invalidation_wins_over_other_confirmation_gates():
    result = SignalLifecycle().evaluate(
        Confirmation(
            symbol="SOLUSDT",
            direction="LONG",
            higher_timeframe_aligned=True,
            in_entry_zone=True,
            retest_confirmed=True,
            five_minute_confirmed=True,
            fifteen_minute_qqe_confirmed=True,
            volume_confirmed=True,
            invalidation_hit=True,
            data_fresh=True,
        )
    )

    assert result.state is SignalState.INVALIDATED
    assert result.actionable is False


def test_mexc_kline_subscription_and_message_parser_normalize_symbol():
    payload = build_kline_subscription("solusdt", "Min5")
    candle = parse_kline_message(
        {
            "channel": "push.kline",
            "symbol": "SOL_USDT",
            "data": {"t": 1_700_000_000_000, "o": 100, "c": 101, "h": 102, "l": 99, "a": 1234},
        }
    )

    assert payload == {"method": "sub.kline", "param": {"symbol": "SOL_USDT", "interval": "Min5"}}
    assert candle is not None
    assert candle.symbol == "SOLUSDT"
    assert candle.timestamp_ms == 1_700_000_000_000
    assert candle.close == 101.0
    assert candle.volume == 1234.0


def test_mexc_parser_normalizes_documented_second_timestamp_to_milliseconds():
    candle = parse_kline_message(
        {
            "channel": "push.kline",
            "symbol": "BTC_USDT",
            "data": {"t": 1_784_192_700, "o": 1, "c": 2, "h": 2, "l": 1, "a": 10},
        }
    )

    assert candle is not None
    assert candle.timestamp_ms == 1_784_192_700_000


def test_mexc_rest_kline_parser_handles_columnar_response():
    from backend.realtime.mexc_stream import parse_rest_klines

    candles = parse_rest_klines(
        "BTC_USDT",
        {
            "success": True,
            "data": {
                "time": [1_700_000_000, 1_700_000_300],
                "open": [100, 101], "close": [101, 102],
                "high": [102, 103], "low": [99, 100], "vol": [9, 10],
            },
        },
    )

    assert [c.timestamp_ms for c in candles] == [1_700_000_000_000, 1_700_000_300_000]
    assert candles[-1].close == 102.0
