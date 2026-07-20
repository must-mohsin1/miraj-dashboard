"""Data-layer resilience: Yahoo→MEXC fallback, timeframe backfill, MEXC retry.

Reproduces the HYPE-USD failure class: Yahoo lists nothing for the symbol
("possibly delisted"), and MEXC signals throttling with an HTTP 200
``success: false`` body that used to become a silent empty frame — blanking
the daily chart and starving DCA/position-alert scans.
"""
import json
import logging
import os

import pandas as pd

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from backend.services import analysis_service
from mirai_core import ohlcv

ALL_TFS = ("weekly", "daily", "4h", "1h", "15m")
EMPTY = pd.DataFrame()


def _frame(rows: int, freq: str = "4h") -> pd.DataFrame:
    index = pd.date_range("2026-07-01", periods=rows, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "Open": [1.0] * rows,
            "High": [2.0] * rows,
            "Low": [0.5] * rows,
            "Close": [1.5] * rows,
            "Volume": [10.0] * rows,
        },
        index=index,
    )


# ── _mexc_contract_candidate ─────────────────────────────────────────────


def test_contract_candidate_maps_usd_and_usdt():
    assert analysis_service._mexc_contract_candidate("HYPE-USD") == "HYPE_USDT"
    assert analysis_service._mexc_contract_candidate("btc-usdt") == "BTC_USDT"


def test_contract_candidate_rejects_unmappable():
    assert analysis_service._mexc_contract_candidate("EURUSD=X") is None
    assert analysis_service._mexc_contract_candidate("-USD") is None


# ── fetch_scan_timeframes: Yahoo→MEXC fallback ───────────────────────────


def test_yahoo_empty_falls_back_to_mexc(monkeypatch):
    yahoo = {tf: EMPTY for tf in ALL_TFS}
    mexc = {tf: _frame(5) for tf in ALL_TFS}
    seen: dict[str, str] = {}

    monkeypatch.setattr(analysis_service.ohlcv, "fetch_all_timeframes", lambda s: yahoo)

    def fake_mexc(symbol):
        seen["symbol"] = symbol
        return mexc

    monkeypatch.setattr(analysis_service.ohlcv, "fetch_mexc_all_timeframes", fake_mexc)

    assert analysis_service.fetch_scan_timeframes("HYPE-USD") is mexc
    assert seen["symbol"] == "HYPE_USDT"


def test_yahoo_data_wins_without_mexc_call(monkeypatch):
    yahoo = {"daily": _frame(3, "1D")}

    monkeypatch.setattr(analysis_service.ohlcv, "fetch_all_timeframes", lambda s: yahoo)

    def boom(symbol):
        raise AssertionError("MEXC must not be called when Yahoo has data")

    monkeypatch.setattr(analysis_service.ohlcv, "fetch_mexc_all_timeframes", boom)

    assert analysis_service.fetch_scan_timeframes("BTC-USD") is yahoo


def test_mexc_empty_returns_yahoo_frames(monkeypatch):
    yahoo = {"daily": EMPTY}
    monkeypatch.setattr(analysis_service.ohlcv, "fetch_all_timeframes", lambda s: yahoo)
    monkeypatch.setattr(
        analysis_service.ohlcv, "fetch_mexc_all_timeframes", lambda s: {"daily": EMPTY}
    )

    assert analysis_service.fetch_scan_timeframes("HYPE-USD") is yahoo


# ── _backfill_missing_timeframes ─────────────────────────────────────────


def test_backfills_daily_from_4h():
    tfs = {"weekly": _frame(4, "7D"), "daily": EMPTY, "4h": _frame(48, "4h")}
    out = analysis_service._backfill_missing_timeframes(tfs)
    daily = out["daily"]
    assert not daily.empty
    assert len(daily) == 8  # 48 four-hour bars = 8 full days
    assert daily["High"].iloc[0] == 2.0
    assert daily["Volume"].iloc[0] == 60.0  # 6 bars/day × 10


def test_backfills_weekly_from_daily():
    tfs = {"weekly": EMPTY, "daily": _frame(28, "1D"), "4h": _frame(2, "4h")}
    out = analysis_service._backfill_missing_timeframes(tfs)
    assert not out["weekly"].empty


def test_backfill_leaves_populated_frames_alone():
    daily = _frame(3, "1D")
    tfs = {"daily": daily, "4h": _frame(8, "4h")}
    out = analysis_service._backfill_missing_timeframes(tfs)
    assert out["daily"] is daily


# ── fetch_mexc_ohlcv: silent-empty body is logged and retried ────────────


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_mexc_silent_empty_body_retries_then_succeeds(monkeypatch, caplog):
    throttled = json.dumps(
        {"success": False, "code": 510, "message": "Requests are too frequent"}
    ).encode()
    ok = json.dumps(
        {
            "success": True,
            "data": {
                "time": [1752969600],
                "open": [1.0],
                "high": [2.0],
                "low": [0.5],
                "close": [1.5],
                "vol": [10.0],
            },
        }
    ).encode()
    bodies = [throttled, ok]

    monkeypatch.setattr(
        ohlcv.request, "urlopen", lambda req, timeout=15: _FakeResponse(bodies.pop(0))
    )
    monkeypatch.setattr(ohlcv.time, "sleep", lambda s: None)

    with caplog.at_level(logging.WARNING):
        frame = ohlcv.fetch_mexc_ohlcv("HYPE_USDT", "Day1")

    assert len(frame) == 1
    assert "no kline data" in caplog.text
    assert "code=510" in caplog.text


def test_mexc_persistent_empty_returns_empty_frame(monkeypatch):
    throttled = json.dumps({"success": False, "code": 510, "message": "busy"}).encode()

    monkeypatch.setattr(
        ohlcv.request, "urlopen", lambda req, timeout=15: _FakeResponse(throttled)
    )
    monkeypatch.setattr(ohlcv.time, "sleep", lambda s: None)

    assert ohlcv.fetch_mexc_ohlcv("HYPE_USDT", "Day1").empty
