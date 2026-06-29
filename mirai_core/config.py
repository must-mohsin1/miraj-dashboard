"""
Mirai Core — Configuration module.

Centralised API endpoints, default thresholds, and trading pair constants.
All live data sources used by the package are defined here.
"""
from __future__ import annotations

# ── CoinGecko ──────────────────────────────────────────────────────────────
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
COINGECKO_COIN = "https://api.coingecko.com/api/v3/coins/{coin_id}"
COINGECKO_DERIVATIVES = "https://api.coingecko.com/api/v3/derivatives"
COINGECKO_MARKET_CHART = (
    "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
)
COINGECKO_USER_AGENT = "Mozilla/5.0"

# ── Fear & Greed ───────────────────────────────────────────────────────────
FEAR_GREED_URL = "https://api.alternative.me/fng/"

# ── Binance Futures ────────────────────────────────────────────────────────
BINANCE_LS_RATIO = (
    "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
)
BINANCE_TOP_LS_RATIO = (
    "https://fapi.binance.com/futures/data/topLongShortAccountRatio"
)

# ── Trading targets ────────────────────────────────────────────────────────
DEFAULT_SYMBOLS = ["BTC-USD", "ETH-USD"]

# ── Macro DataFrame ────────────────────────────────────────────────────────
MACRO_KEYS = ["btc_d", "usdt_d", "dxy", "fear_greed", "long_short_ratio"]

# ── Chart pattern thresholds ───────────────────────────────────────────────
PATTERN_PROMINENCE_FACTOR = 0.5  # scipy find_peaks prominence = std * factor
PATTERN_DISTANCE = 3
DOUBLE_TOP_TOLERANCE = 0.03  # 3 %
DOUBLE_BOTTOM_TOLERANCE = 0.03
HANDS_SHOULDER_EQUALITY = 0.05  # shoulder symmetry tolerance

# ── Indicator defaults ─────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
BB_PERIOD = 20
BB_STD = 2.0
BB_SQUEEZE_THRESHOLD = 0.8  # current width < 80 % of avg 20 → squeeze
EMAS_SHORT = 20
EMAS_MEDIUM = 50
EMAS_LONG = 200
EMA_RIBBON_SPANS = [20, 25, 30, 35, 40, 45, 50, 55]

# ── QQE Mod ────────────────────────────────────────────────────────────────
QQE_RSI_PERIOD = 14
QQE_SMOOTH = 5
QQE_SF = 4.236  # safety factor for dynamic trailing stop
QQE_VOL_BUY_HIGH = 0.55
QQE_VOL_SELL_LOW = 0.45

# ── SMC ────────────────────────────────────────────────────────────────────
SMC_LOOKBACK = 100
SWING_DISTANCE = 3
SWING_PROMINENCE = 0.5
LIQUIDITY_RECOVERY_BARS = 3

# ── Confluence scoring ─────────────────────────────────────────────────────
SCORE_TRADE_THRESHOLD = 10
SCORE_MAX = 30
REGIME_WEIGHT = 9
LOCATION_WEIGHT = 8
CONFIRMATION_WEIGHT = 9
VOLUME_RETEST_WEIGHT = 3
RISK_WEIGHT = 4

# ── Trade plan ─────────────────────────────────────────────────────────────
RSI_ENTRY_THRESHOLDS = (30, 24, 16)  # RSI values for 3 entries
RSI_ENTRY_ALLOCATIONS = (0.20, 0.20, 0.60)
RSI_SHORT_ENTRY_L1 = 80
RSI_SHORT_ENTRY_L2 = 92
RSI_SHORT_ENTRY_L3 = 95
