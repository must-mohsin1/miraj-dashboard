"""
Macro data fetching — no API keys required.

Fetches:
- BTC.D / ETH.D / USDT.D from CoinGecko
- DXY from Yahoo Finance
- Fear & Greed Index from alternative.me
- Binance long/short ratio for BTC and ETH
- Optionally BTC.D historical via 13-coin workaround
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pandas as pd
import requests
import yfinance as yf

from mirai_core import config
from mirai_core.ohlcv import flat_df

logger = logging.getLogger(__name__)


# ── CoinGecko ──────────────────────────────────────────────────────────────

def fetch_coingecko_global() -> dict[str, Any]:
    """Fetch BTC.D, ETH.D, and total market cap from CoinGecko."""
    r = requests.get(config.COINGECKO_GLOBAL, timeout=15)
    r.raise_for_status()
    data = r.json()["data"]
    return {
        "btc_d": data["market_cap_percentage"]["btc"],
        "eth_d": data["market_cap_percentage"]["eth"],
        "total_mcap": data["total_market_cap"]["usd"],
        "altcoin_mcap": (
            data["total_market_cap"]["usd"]
            - data["market_cap_percentage"]["btc"] / 100
            * data["total_market_cap"]["usd"]
        ),
    }


def fetch_usdt_dominance() -> float:
    """Fetch USDT market cap and compute USDT.D = USDT_mcap / total_mcap * 100."""
    global_data = fetch_coingecko_global()
    r2 = requests.get(
        config.COINGECKO_COIN.format(coin_id="tether"), timeout=15
    )
    r2.raise_for_status()
    usdt_mcap = r2.json()["market_data"]["market_cap"]["usd"]
    total = global_data["total_mcap"]
    return usdt_mcap / total * 100 if total > 0 else 0.0


# ── Fear & Greed ───────────────────────────────────────────────────────────

def fetch_fear_greed() -> dict[str, Any]:
    """Fetch Fear & Greed Index value and classification."""
    r = requests.get(config.FEAR_GREED_URL, params={"limit": 1}, timeout=10)
    r.raise_for_status()
    return r.json()["data"][0]


# ── Binance L/S ────────────────────────────────────────────────────────────

def fetch_long_short_ratio(
    symbol: str = "BTCUSDT",
    period: str = "4h",
    limit: int = 1,
) -> Optional[dict[str, Any]]:
    """Fetch Binance global long/short account ratio.

    Returns None on error.
    """
    try:
        r = requests.get(
            config.BINANCE_LS_RATIO,
            params={"symbol": symbol, "period": period, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            return data[0]
        return None
    except Exception as exc:
        logger.warning("Binance L/S fetch failed for %s: %s", symbol, exc)
        return None


# ── DXY ────────────────────────────────────────────────────────────────────

def fetch_dxy() -> Optional[float]:
    """Fetch DXY (US Dollar Index) latest close via yfinance."""
    try:
        dxy = flat_df(
            yf.download("DX-Y.NYB", period="5d", interval="1d", progress=False)
        )
        if not dxy.empty:
            return float(dxy["Close"].iloc[-1])
        return None
    except Exception as exc:
        logger.warning("DXY fetch failed: %s", exc)
        return None


# ── S&P 500 ────────────────────────────────────────────────────────────────

def fetch_sp500() -> Optional[float]:
    """Fetch S&P 500 latest close."""
    try:
        sp = flat_df(
            yf.download("^GSPC", period="5d", interval="1d", progress=False)
        )
        if not sp.empty:
            return float(sp["Close"].iloc[-1])
        return None
    except Exception as exc:
        logger.warning("S&P 500 fetch failed: %s", exc)
        return None


# ── Nasdaq ─────────────────────────────────────────────────────────────────

def fetch_nasdaq() -> Optional[float]:
    """Fetch Nasdaq Composite latest close."""
    try:
        nq = flat_df(
            yf.download("^IXIC", period="5d", interval="1d", progress=False)
        )
        if not nq.empty:
            return float(nq["Close"].iloc[-1])
        return None
    except Exception as exc:
        logger.warning("Nasdaq fetch failed: %s", exc)
        return None


# ── Full macro snapshot ────────────────────────────────────────────────────

def fetch_macro_data() -> dict[str, Any]:
    """Fetch all macro indicators and return a single dict.

    Keys: btc_d, eth_d, usdt_d, total_mcap, fear_greed, dxy,
          long_short_ratio_btc, sp500, nasdaq.
    """
    result: dict[str, Any] = {}

    # CoinGecko global
    try:
        global_data = fetch_coingecko_global()
        result["btc_d"] = global_data["btc_d"]
        result["eth_d"] = global_data["eth_d"]
        result["total_mcap"] = global_data["total_mcap"]
    except Exception as exc:
        logger.warning("Failed to fetch CoinGecko global: %s", exc)
        result["btc_d"] = result["eth_d"] = result["total_mcap"] = None

    # USDT Dominance
    try:
        result["usdt_d"] = fetch_usdt_dominance()
    except Exception as exc:
        logger.warning("Failed to fetch USDT.D: %s", exc)
        result["usdt_d"] = None

    # Fear & Greed
    try:
        fng = fetch_fear_greed()
        result["fear_greed"] = {
            "value": int(fng["value"]),
            "classification": fng["value_classification"],
        }
    except Exception as exc:
        logger.warning("Failed to fetch Fear & Greed: %s", exc)
        result["fear_greed"] = None

    # DXY
    result["dxy"] = fetch_dxy()

    # Traditional markets
    result["sp500"] = fetch_sp500()
    result["nasdaq"] = fetch_nasdaq()

    # L/S Ratios
    ls_btc = fetch_long_short_ratio("BTCUSDT")
    result["long_short_ratio_btc"] = (
        float(ls_btc["longShortRatio"]) if ls_btc else None
    )
    ls_eth = fetch_long_short_ratio("ETHUSDT")
    result["long_short_ratio_eth"] = (
        float(ls_eth["longShortRatio"]) if ls_eth else None
    )

    return result


# ── BTC.D historical (13‑coin workaround) ──────────────────────────────────

BTC_D_COINS = [
    "bitcoin",
    "ethereum",
    "tether",
    "binancecoin",
    "solana",
    "ripple",
    "usd-coin",
    "cardano",
    "dogecoin",
    "avalanche-2",
    "tron",
    "chainlink",
    "polkadot",
]


def fetch_btcd_historical(
    days: int = 90,
) -> list[tuple[int, float]]:
    """Compute BTC.D historical series from 13 individual coins.

    Returns list of (day_timestamp, btc_dominance_pct) sorted chronologically.
    """
    headers = {"User-Agent": config.COINGECKO_USER_AGENT}
    total_mcaps: dict[int, float] = {}
    btc_mcaps: dict[int, float] = {}

    for coin_id in BTC_D_COINS:
        try:
            r = requests.get(
                config.COINGECKO_MARKET_CHART.format(coin_id=coin_id),
                params={"vs_currency": "usd", "days": str(days)},
                headers=headers,
                timeout=15,
            )
            if r.status_code == 200:
                for ts, mc in r.json().get("market_caps", []):
                    day = int(ts / 86_400_000)
                    total_mcaps[day] = total_mcaps.get(day, 0) + mc
                    if coin_id == "bitcoin":
                        btc_mcaps[day] = mc
            time.sleep(0.5)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", coin_id, exc)

    series: list[tuple[int, float]] = []
    for day in sorted(total_mcaps):
        if day in btc_mcaps and total_mcaps[day] > 0:
            series.append((day, btc_mcaps[day] / total_mcaps[day] * 100))
    return series
