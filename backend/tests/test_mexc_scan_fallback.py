import asyncio
import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

from backend.routes import scan
from backend.services import analysis_service


def test_invalid_yahoo_symbol_uses_catalogue_verified_mexc_contract(monkeypatch):
    monkeypatch.setattr(scan, "fetch_mexc_contract_catalogue", _catalogue({"HYPE_USDT"}))

    assert asyncio.run(scan.resolve_mexc_scan_symbol("HYPE-USD")) == "HYPE_USDT"


def _catalogue(symbols):
    async def result():
        return frozenset(symbols)

    return result


def test_scan_uses_mexc_candles_when_catalogue_resolves_symbol(monkeypatch):
    frames = {"daily": object()}

    monkeypatch.setattr(
        analysis_service.ohlcv,
        "fetch_mexc_all_timeframes",
        lambda symbol: frames,
        raising=False,
    )

    assert analysis_service.fetch_scan_timeframes("HYPE-USD", mexc_symbol="HYPE_USDT") is frames
