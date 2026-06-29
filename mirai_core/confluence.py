"""
Confluence scoring engine.

Scores a trade setup from 0-30 based on:
- Regime (max 9)
- Location (max 8)
- Confirmation (max 9)
- Volume & Retest (max 3)
- Risk (max 4)

Trade decision: score >= SCORE_TRADE_THRESHOLD (default 10).
"""
from __future__ import annotations

from typing import Any

from mirai_core import config


class ConfluenceResult:
    """Holds confluence scoring breakdown and final decision."""

    def __init__(self) -> None:
        self.regime_score: float = 0.0
        self.location_score: float = 0.0
        self.confirmation_score: float = 0.0
        self.volume_retest_score: float = 0.0
        self.risk_score: float = 0.0
        self.regime_breakdown: dict[str, bool] = {}
        self.location_breakdown: dict[str, bool] = {}
        self.confirmation_breakdown: dict[str, bool] = {}
        self.volume_retest_breakdown: dict[str, bool] = {}
        self.risk_breakdown: dict[str, bool] = {}

    @property
    def total(self) -> float:
        return (
            self.regime_score
            + self.location_score
            + self.confirmation_score
            + self.volume_retest_score
            + self.risk_score
        )

    @property
    def trade_decision(self) -> bool:
        return self.total >= config.SCORE_TRADE_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": {"score": self.regime_score, "breakdown": self.regime_breakdown},
            "location": {
                "score": self.location_score,
                "breakdown": self.location_breakdown,
            },
            "confirmation": {
                "score": self.confirmation_score,
                "breakdown": self.confirmation_breakdown,
            },
            "volume_retest": {
                "score": self.volume_retest_score,
                "breakdown": self.volume_retest_breakdown,
            },
            "risk": {"score": self.risk_score, "breakdown": self.risk_breakdown},
            "total": self.total,
            "trade_decision": self.trade_decision,
        }


def score(
    data: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ConfluenceResult:
    """Compute confluence score from analysis data.

    Args:
        data: A dict with keys matching the score categories (regime, location, ...).
              Alternatively pass keyword arguments directly.

    Returns:
        ConfluenceResult with breakdown and decision.
    """
    result = ConfluenceResult()

    if data is None:
        data = kwargs

    # ── Regime (max 9) ──────────────────────────────────────────────────
    r = result.regime_breakdown

    # Weekly structure aligned
    r["weekly_structure"] = bool(data.get("weekly_structure_aligned", False))
    if r["weekly_structure"]:
        result.regime_score += 2.0

    # Daily structure aligned
    r["daily_structure"] = bool(data.get("daily_structure_aligned", False))
    if r["daily_structure"]:
        result.regime_score += 2.0

    # BTC.D aligned
    r["btc_d_aligned"] = bool(data.get("btc_d_aligned", False))
    if r["btc_d_aligned"]:
        result.regime_score += 1.0

    # Weekly 200MA position
    r["weekly_200ma"] = bool(data.get("weekly_200ma_position", False))
    if r["weekly_200ma"]:
        result.regime_score += 1.0

    # USDT.D favourable
    r["usdt_d_favourable"] = bool(data.get("usdt_d_favourable", False))
    if r["usdt_d_favourable"]:
        result.regime_score += 1.0

    # Bull Market Support Band
    r["bmsb"] = bool(data.get("bmsb_aligned", False))
    if r["bmsb"]:
        result.regime_score += 1.0

    # Fear & Greed aligned
    r["fear_greed_aligned"] = bool(data.get("fear_greed_aligned", False))
    if r["fear_greed_aligned"]:
        result.regime_score += 1.0

    # ── Location (max 8) ────────────────────────────────────────────────
    l = result.location_breakdown

    l["demand_supply_zone"] = bool(data.get("demand_supply_zone", False))
    if l["demand_supply_zone"]:
        result.location_score += 2.0

    l["ote_overlap"] = bool(data.get("ote_overlap", False))
    if l["ote_overlap"]:
        result.location_score += 2.0

    l["order_block_at_zone"] = bool(data.get("order_block_at_zone", False))
    if l["order_block_at_zone"]:
        result.location_score += 1.0

    l["fvg_at_zone"] = bool(data.get("fvg_at_zone", False))
    if l["fvg_at_zone"]:
        result.location_score += 1.0

    l["liquidity_grab_before_ote"] = bool(
        data.get("liquidity_grab_before_ote", False)
    )
    if l["liquidity_grab_before_ote"]:
        result.location_score += 1.0

    l["trend_line_at_zone"] = bool(data.get("trend_line_at_zone", False))
    if l["trend_line_at_zone"]:
        result.location_score += 1.0

    # ── Confirmation (max 9) ────────────────────────────────────────────
    c = result.confirmation_breakdown

    c["h4_structure"] = bool(data.get("h4_structure_aligned", False))
    if c["h4_structure"]:
        result.confirmation_score += 1.0

    c["daily_rsi_confirms"] = bool(data.get("daily_rsi_confirms", False))
    if c["daily_rsi_confirms"]:
        result.confirmation_score += 1.0

    c["h4_rsi_confirms"] = bool(data.get("h4_rsi_confirms", False))
    if c["h4_rsi_confirms"]:
        result.confirmation_score += 1.0

    c["bb_not_squeezing"] = bool(data.get("bb_not_squeezing", False))
    if c["bb_not_squeezing"]:
        result.confirmation_score += 1.0

    c["qqe_aligned"] = bool(data.get("qqe_aligned", False))
    if c["qqe_aligned"]:
        result.confirmation_score += 1.0

    c["m15_structure"] = bool(data.get("m15_structure_aligned", False))
    if c["m15_structure"]:
        result.confirmation_score += 1.0

    c["rsi_divergence"] = bool(data.get("rsi_divergence_present", False))
    if c["rsi_divergence"]:
        result.confirmation_score += 1.0

    c["chart_pattern"] = bool(data.get("chart_pattern_confirmed", False))
    if c["chart_pattern"]:
        result.confirmation_score += 1.0

    c["ema_ribbon"] = bool(data.get("ema_ribbon_aligned", False))
    if c["ema_ribbon"]:
        result.confirmation_score += 1.0

    # ── Volume & Retest (max 3) ─────────────────────────────────────────
    v = result.volume_retest_breakdown

    v["volume_confirming"] = bool(data.get("volume_confirming", False))
    if v["volume_confirming"]:
        result.volume_retest_score += 1.0

    v["retest_confirmed"] = bool(data.get("retest_confirmed", False))
    if v["retest_confirmed"]:
        result.volume_retest_score += 1.0

    v["no_fakeout"] = bool(data.get("no_fakeout", False))
    if v["no_fakeout"]:
        result.volume_retest_score += 1.0

    # ── Risk (max 4) ────────────────────────────────────────────────────
    ri = result.risk_breakdown

    ri["target_2r"] = bool(data.get("target_2r_available", False))
    if ri["target_2r"]:
        result.risk_score += 2.0

    ri["clean_stop"] = bool(data.get("clean_stop_level", False))
    if ri["clean_stop"]:
        result.risk_score += 1.0

    ri["no_news_risk"] = bool(data.get("no_news_risk", False))
    if ri["no_news_risk"]:
        result.risk_score += 1.0

    return result
