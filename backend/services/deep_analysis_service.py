"""Deep analysis service — generates a comprehensive narrative from scan results.

The deep scan re-runs the full pipeline (bypassing cache) and produces a
rich textual analysis of the current trading picture: trend alignment,
QQE consensus, market structure coherence, pattern implications, volume
confirmation, key levels, risk factors, and an overall verdict.
"""

from __future__ import annotations

from typing import Any

logger = __import__("logging").getLogger(__name__)


def generate_deep_analysis(result: dict[str, Any]) -> dict[str, Any]:
    """Build a comprehensive analysis narrative from the full scan result.

    Returns a dict with keys:
      summary         — one-line verdict
      detailed_analysis — multi-paragraph narrative broken into sections
      risk_factors    — list of identified risk items
      key_levels      — dict of notable price levels
      timeframe_breakdown — per-TF assessment
    """
    sections: list[dict[str, str]] = []
    risk_factors: list[str] = []
    key_levels: dict[str, float | None] = {}
    tf_breakdown: dict[str, str] = {}

    # ── Extract signals from result ────────────────────────────────
    symbol = result.get("symbol", "")
    conf_score = result.get("confluence_score", 0) or 0
    overall = result.get("overall_score", 0) or 0
    qqe_signals = result.get("qqe_signals", {}) or {}
    structure = result.get("structure", {}) or {}
    patterns = result.get("patterns", {}) or {}
    bmsb = result.get("bmsb", {}) or {}
    trade_plan_flat = result.get("trade_plan_flat", {}) or {}
    scores = result.get("scores", {}) or {}
    indicators = result.get("indicators", {}) or {}
    macro_data = result.get("macro_data", {}) or {}

    direction = (trade_plan_flat.get("direction") or "NEUTRAL").upper()
    entry = trade_plan_flat.get("entry")
    stop_loss = trade_plan_flat.get("stop_loss")
    targets = [
        trade_plan_flat.get("target_1"),
        trade_plan_flat.get("target_2"),
        trade_plan_flat.get("target_3"),
    ]

    # ── 1. Trend alignment (EMA-based) ─────────────────────────────
    _build_trend_section(indicators, sections, tf_breakdown)

    # ── 2. QQE consensus ───────────────────────────────────────────
    _build_qqe_section(qqe_signals, sections, tf_breakdown, risk_factors)

    # ── 3. Market structure ────────────────────────────────────────
    _build_structure_section(structure, sections, tf_breakdown, risk_factors)

    # ── 4. Pattern analysis ────────────────────────────────────────
    _build_pattern_section(patterns, sections, risk_factors)

    # ── 5. BMSB / macro context ────────────────────────────────────
    _build_macro_section(bmsb, macro_data, sections, risk_factors)

    # ── 6. Score breakdown analysis ────────────────────────────────
    _build_score_section(scores, conf_score, sections, risk_factors)

    # ── 7. Key levels ──────────────────────────────────────────────
    key_levels = {"entry": entry, "stop_loss": stop_loss}
    for i, t in enumerate(targets, 1):
        if t is not None:
            key_levels[f"target_{i}"] = t
    # Add SMC levels if present
    smc = result.get("smc", {}) or {}
    obs = smc.get("order_blocks", [])
    if obs and isinstance(obs, list):
        for i, ob in enumerate(obs[:3]):
            zone = ob.get("zone", (None, None))
            if zone[0] is not None:
                key_levels[f"ob_{i+1}_low"] = float(zone[0])
                key_levels[f"ob_{i+1}_high"] = float(zone[1])
    fvgs = smc.get("fvgs", [])
    if fvgs and isinstance(fvgs, list):
        for i, fvg in enumerate(fvgs[:2]):
            key_levels[f"fvg_{i+1}_low"] = float(fvg.get("start", 0)) if fvg.get("start") else None
            key_levels[f"fvg_{i+1}_high"] = float(fvg.get("end", 0)) if fvg.get("end") else None

    # ── 8. Overall verdict ─────────────────────────────────────────
    bullish_signals = 0
    bearish_signals = 0
    neutral_signals = 0

    # Count QQE signals
    for tf_name, sig in qqe_signals.items():
        if isinstance(sig, dict):
            trend = sig.get("trend", "NEUTRAL")
            if trend == "GREEN":
                bullish_signals += 1
            elif trend == "RED":
                bearish_signals += 1
            else:
                neutral_signals += 1

    # Count structure alignment
    for tf_name, s in structure.items():
        if isinstance(s, dict):
            label = s.get("label", "")
            if label in ("HH", "HL"):
                bullish_signals += 1
            elif label in ("LH", "LL"):
                bearish_signals += 1
            else:
                neutral_signals += 1

    # BMSB regime
    if bmsb.get("regime") == "bull":
        bullish_signals += 1
    elif bmsb.get("regime") == "bear":
        bearish_signals += 1

    # Score-based
    if conf_score >= 20:
        bullish_signals += 2
    elif conf_score <= 10:
        bearish_signals += 2
    else:
        neutral_signals += 1

    # Direction from trade plan
    if direction == "LONG":
        bullish_signals += 2
    elif direction == "SHORT":
        bearish_signals += 2

    total = bullish_signals + bearish_signals + neutral_signals
    if total > 0:
        bias_pct = round((bullish_signals / total) * 100, 0)
    else:
        bias_pct = 50

    if bias_pct >= 65:
        verdict = f"Bullish bias ({bias_pct:.0f}%) — {symbol} shows strong bullish alignment across multiple timeframes. {_verdict_detail(direction, 'LONG')}"
    elif bias_pct <= 35:
        verdict = f"Bearish bias ({bias_pct:.0f}%) — {symbol} shows bearish alignment. {_verdict_detail(direction, 'SHORT')}"
    else:
        verdict = f"Neutral / mixed ({bias_pct:.0f}%) — conflicting signals across timeframes. Waiting for clearer confluence is advised."

    summary = verdict

    # ── Assemble ───────────────────────────────────────────────────
    # Deduplicate risk factors
    seen_risks: set[str] = set()
    unique_risks: list[str] = []
    for r in risk_factors:
        if r not in seen_risks:
            seen_risks.add(r)
            unique_risks.append(r)

    return {
        "summary": summary,
        "detailed_analysis": sections,
        "risk_factors": unique_risks,
        "key_levels": key_levels,
        "timeframe_breakdown": tf_breakdown,
        "bullish_signals": bullish_signals,
        "bearish_signals": bearish_signals,
        "neutral_signals": neutral_signals,
        "bias_percent": bias_pct,
    }


# ── Section builders ──────────────────────────────────────────────────────


def _build_trend_section(
    indicators: dict[str, Any],
    sections: list[dict[str, str]],
    tf_breakdown: dict[str, str],
) -> None:
    """Analyze EMA / RSI trends across timeframes."""
    trend_lines: list[str] = []
    for tf in ("weekly", "daily", "4h", "1h", "15m"):
        ind = indicators.get(tf, {})
        if not isinstance(ind, dict) or ind.get("error"):
            tf_breakdown[tf] = "No data"
            continue

        parts: list[str] = []

        # RSI
        rsi = ind.get("rsi")
        if rsi is not None:
            rsi_val = float(rsi)
            if rsi_val > 70:
                parts.append(f"RSI {rsi_val:.0f} (overbought)")
            elif rsi_val < 30:
                parts.append(f"RSI {rsi_val:.0f} (oversold)")
            elif rsi_val > 60:
                parts.append(f"RSI {rsi_val:.0f} (bullish)")
            elif rsi_val < 40:
                parts.append(f"RSI {rsi_val:.0f} (bearish)")
            else:
                parts.append(f"RSI {rsi_val:.0f} (neutral)")

        # BB squeeze
        bb_squeeze = ind.get("bb_squeeze")
        if bb_squeeze:
            parts.append("BB squeeze")
            trend_lines.append(f"{tf}: BB squeeze — volatility contraction, breakout imminent")

        # Golden/death cross
        cross = ind.get("golden_death_cross")
        if cross:
            parts.append(f"{cross}")
            trend_lines.append(f"{tf}: {cross}")

        tf_breakdown[tf] = "; ".join(parts) if parts else "Neutral"

    if trend_lines:
        sections.append({
            "heading": "Trend Analysis",
            "body": " ".join(trend_lines),
        })


def _build_qqe_section(
    qqe_signals: dict[str, Any],
    sections: list[dict[str, str]],
    tf_breakdown: dict[str, str],
    risk_factors: list[str],
) -> None:
    """Analyze QQE signal alignment."""
    if not qqe_signals:
        return

    green_tfs: list[str] = []
    red_tfs: list[str] = []
    neutral_tfs: list[str] = []
    strong_tfs: list[str] = []

    for tf, sig in qqe_signals.items():
        if not isinstance(sig, dict):
            continue
        trend = sig.get("trend", "NEUTRAL")
        strength = sig.get("strength", "NONE")
        if trend == "GREEN":
            green_tfs.append(tf)
        elif trend == "RED":
            red_tfs.append(tf)
        else:
            neutral_tfs.append(tf)
        if strength == "STRONG":
            strong_tfs.append(tf)

    qqe_lines: list[str] = []

    if green_tfs and not red_tfs:
        qqe_lines.append(
            f"QQE is GREEN across all {len(green_tfs)} timeframes — strong bullish consensus."
        )
    elif red_tfs and not green_tfs:
        qqe_lines.append(
            f"QQE is RED across all {len(red_tfs)} timeframes — strong bearish consensus."
        )
    elif green_tfs and red_tfs:
        qqe_lines.append(
            f"Mixed QQE: GREEN on {', '.join(green_tfs)}, RED on {', '.join(red_tfs)}. "
            f"{'⚠️  Trend conflict — higher-TF directional bias should prevail.' if neutral_tfs else ''}"
        )
        risk_factors.append(
            f"QQE conflict: GREEN on {', '.join(green_tfs)} vs RED on {', '.join(red_tfs)}"
        )

    if strong_tfs:
        qqe_lines.append(
            f"Volume-confirmed (STRONG) on: {', '.join(strong_tfs)}"
        )

    if qqe_lines:
        sections.append({"heading": "QQE Signal Consensus", "body": " ".join(qqe_lines)})


def _build_structure_section(
    structure: dict[str, Any],
    sections: list[dict[str, str]],
    tf_breakdown: dict[str, str],
    risk_factors: list[str],
) -> None:
    """Analyze market structure alignment."""
    if not structure:
        return

    bullish_tfs: list[str] = []
    bearish_tfs: list[str] = []
    unknown_tfs: list[str] = []

    for tf, s in structure.items():
        if not isinstance(s, dict):
            continue
        label = s.get("label", "")
        if label in ("HH", "HL"):
            bullish_tfs.append(tf)
        elif label in ("LH", "LL"):
            bearish_tfs.append(tf)
        else:
            unknown_tfs.append(tf)

    struct_lines: list[str] = []

    if bullish_tfs and not bearish_tfs:
        struct_lines.append(
            f"Market structure is bullish across all {len(bullish_tfs)} timeframes "
            f"({', '.join(bullish_tfs)}). Trend-following bias."
        )
    elif bearish_tfs and not bullish_tfs:
        struct_lines.append(
            f"Market structure is bearish across all {len(bearish_tfs)} timeframes "
            f"({', '.join(bearish_tfs)}). Trend-following bias."
        )
    elif bullish_tfs and bearish_tfs:
        struct_lines.append(
            f"Structure conflict: bullish on {', '.join(bullish_tfs)}, "
            f"bearish on {', '.join(bearish_tfs)}."
        )
        risk_factors.append(
            f"Structure conflict: bullish on {', '.join(bullish_tfs)} vs "
            f"bearish on {', '.join(bearish_tfs)}"
        )

    if struct_lines:
        sections.append({"heading": "Market Structure", "body": " ".join(struct_lines)})

    # Update tf_breakdown with structure info
    for tf, s in structure.items():
        if isinstance(s, dict):
            label = s.get("label", "")
            detail = s.get("detail", "")
            existing = tf_breakdown.get(tf, "")
            struct_part = f"Structure: {label}"
            if detail:
                struct_part += f" ({detail})"
            if existing and existing != "No data":
                tf_breakdown[tf] = f"{existing} | {struct_part}"
            else:
                tf_breakdown[tf] = struct_part


def _build_pattern_section(
    patterns: dict[str, Any],
    sections: list[dict[str, str]],
    risk_factors: list[str],
) -> None:
    """Summarize detected chart patterns."""
    detected = patterns.get("detected", []) if isinstance(patterns, dict) else []
    if not detected:
        return

    bullish_patterns: list[str] = []
    bearish_patterns: list[str] = []
    confirmed: list[str] = []

    for p in detected:
        if not isinstance(p, dict):
            continue
        name = p.get("name") or p.get("pattern") or "Unknown"
        sig = p.get("signal") or p.get("direction") or ""
        is_confirmed = p.get("confirmed", False)

        if sig and "bull" in sig.lower():
            bullish_patterns.append(name)
        elif sig and "bear" in sig.lower():
            bearish_patterns.append(name)

        if is_confirmed:
            confirmed.append(name)

    lines: list[str] = []
    if bullish_patterns:
        lines.append(f"Bullish: {', '.join(bullish_patterns)}")
    if bearish_patterns:
        lines.append(f"Bearish: {', '.join(bearish_patterns)}")
    if confirmed:
        lines.append(f"Confirmed: {', '.join(confirmed)} — higher reliability.")
    else:
        lines.append("No patterns confirmed yet — prices may need to react at levels.")

    sections.append({"heading": "Chart Pattern Analysis", "body": " | ".join(lines)})


def _build_macro_section(
    bmsb: dict[str, Any],
    macro_data: dict[str, Any],
    sections: list[dict[str, str]],
    risk_factors: list[str],
) -> None:
    """Macro context and BMSB regime."""
    macro_lines: list[str] = []

    # BMSB
    if bmsb:
        regime = bmsb.get("regime", "").upper()
        status = bmsb.get("status", "")
        if regime == "BULL":
            macro_lines.append(
                f"BMSB regime: BULL (price ${bmsb.get('current_price', '?')} above "
                f"20w SMA ${bmsb.get('sma_20w', '?'):.2f} / 21w EMA ${bmsb.get('ema_21w', '?'):.2f})"
            )
        elif regime == "BEAR":
            macro_lines.append(
                f"BMSB regime: BEAR (price ${bmsb.get('current_price', '?')} below "
                f"support band). ⚠️  Bear market caution."
            )
            risk_factors.append("BMSB: price below bull market support band (bear regime)")

    # Macro indicators
    if macro_data:
        btc_d = macro_data.get("btc_d")
        if btc_d is not None:
            macro_lines.append(f"BTC dominance: {btc_d:.1f}%{' — alt season unlikely' if btc_d and float(btc_d) > 55 else ''}")
        fg = macro_data.get("fear_greed")
        if fg and isinstance(fg, dict):
            fg_val = fg.get("value")
            fg_label = fg.get("label", "")
            if fg_val is not None:
                macro_lines.append(f"Fear & Greed: {fg_val} ({fg_label})")
                if int(fg_val) > 80:
                    risk_factors.append(f"Extreme Greed ({fg_val}) — caution for long entries")
                elif int(fg_val) < 20:
                    risk_factors.append(f"Extreme Fear ({fg_val}) — potential buying opportunity")

    if macro_lines:
        sections.append({"heading": "Macro Context", "body": " | ".join(macro_lines)})


def _build_score_section(
    scores: dict[str, Any],
    conf_score: float,
    sections: list[dict[str, str]],
    risk_factors: list[str],
) -> None:
    """Analyze category scores and highlight weak areas."""
    if not scores:
        return

    weak_categories: list[str] = []
    strong_categories: list[str] = []

    cat_max: dict[str, float] = {
        "regime": 6, "location": 6, "confirmation": 6,
        "volume_retest": 5, "risk": 5,
    }

    for cat, val in scores.items():
        if val is None:
            continue
        max_val = cat_max.get(cat, 6)
        try:
            frac = float(val) / max_val
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        label = cat.replace("_", " ").title()
        if frac >= 0.6:
            strong_categories.append(label)
        elif frac < 0.4:
            weak_categories.append(label)

    lines: list[str] = [f"Overall confluence score: {conf_score:.1f} / 30"]

    if strong_categories:
        lines.append(f"Strong areas: {', '.join(strong_categories)}.")
    if weak_categories:
        lines.append(f"Weak areas: {', '.join(weak_categories)} — these need improvement.")
        for w in weak_categories:
            risk_factors.append(f"Weak {w.lower()} score — check for missing confluence")

    if conf_score >= 20:
        lines.append("Score is in the green zone (≥20) — valid trade setup.")
    elif conf_score < 10:
        lines.append("Score is low (<10) — conditions do not favour a trade.")
        risk_factors.append(f"Low confluence score ({conf_score:.1f})")
    else:
        lines.append("Score in neutral range (10–20) — conditions are developing.")

    sections.append({"heading": "Confluence Score Breakdown", "body": " ".join(lines)})


def _verdict_detail(actual_dir: str, bias_dir: str) -> str:
    """Generate verdict detail based on direction alignment."""
    if actual_dir == bias_dir:
        return "Trade plan direction aligns with the bias — directional confidence."
    elif actual_dir == "NEUTRAL":
        return "Trade plan is neutral — awaiting confirmation."
    else:
        return (
            f"⚠️  Trade plan suggests {actual_dir} but the bias is {bias_dir}. "
            "This divergence warrants extra caution."
        )
