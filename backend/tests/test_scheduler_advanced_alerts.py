from backend.scheduler import select_advanced_signals


def test_select_advanced_signals_uses_active_alert_types_not_symbols():
    signals = [
        {"type": "rsi_oversold"},
        {"type": "ema_cross_bullish"},
        {"type": "volume_spike"},
    ]

    selected = select_advanced_signals(signals, {"rsi", "volume_spike"})

    assert list(selected) == ["rsi", "volume_spike"]
    assert selected["rsi"][0]["type"] == "rsi_oversold"
