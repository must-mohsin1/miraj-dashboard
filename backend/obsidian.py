"""Obsidian vault sync service — writes analysis reports as markdown + chart PNGs.

After each scan, the sync service checks user settings (vault path, sync toggle)
and writes a formatted markdown report and mplfinance chart PNG to the vault.

Acceptance criteria
--------------------
- After analysis, writes ``<vault>/crypto/Crypto_Pair_Analysis_<date>.md`` with full report
- Saves mplfinance chart PNGs to ``<vault>/crypto/analysis/``
- Markdown includes: confluence score, score breakdown, trade plan, entry/stop/target levels
- Configurable vault path per user (default: empty — sync disabled)
- Path validation: verify vault path exists before writing; error shown if invalid
- Sync toggle per pair in user settings
- Daily digest also synced as ``<vault>/crypto/daily_digest_<date>.md``
- No vault write if sync disabled or path not configured

Vault path storage
-------------------
Vault path is stored per-user in the ``PairSetting`` model using a special pair value
``__VAULT__``.  The ``settings`` JSON dict has key ``"obsidian_vault_path"``.

Sync toggles per pair
----------------------
Each pair's own ``PairSetting.settings`` dict has key ``"obsidian_sync"`` (default ``True``).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

# ── Ensure mirai_core is importable ──────────────────────────────────────
import sys

_MIRAI_CORE_PATH = os.environ.get(
    "MIRAI_CORE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mirai_core"),
)
_MIRAI_PARENT = os.path.dirname(_MIRAI_CORE_PATH)
if _MIRAI_PARENT not in sys.path:
    sys.path.insert(0, _MIRAI_PARENT)

from mirai_core import charts as mf_charts  # noqa: E402

from backend.models import PairSetting  # noqa: E402

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

VAULT_SETTINGS_PAIR = "__VAULT__"  # Special pair key for user-level vault settings
CRYPTO_DIR = "crypto"
ANALYSIS_DIR = "analysis"
REPORT_FILE = "Crypto_Pair_Analysis_{pair}_{date}.md"
CHART_FILE = "{pair}_{date}.png"
DIGEST_FILE = "daily_digest_{date}.md"


# ── Public API ────────────────────────────────────────────────────────────


def sync_scan_result(
    user_id: int,
    pair: str,
    scan_result: dict[str, Any],
    vault_path: str,
) -> bool:
    """Write *scan_result* for *pair* (user *user_id*) to the Obsidian *vault_path*.

    Returns ``True`` when the markdown report (and any chart PNG) was written
    successfully, ``False`` when the vault path doesn't exist or another error
    occurs (logged but not raised).

    This is a synchronous function suitable for calling from ``asyncio.to_thread``
    or a thread pool.
    """
    # ── Path validation ──────────────────────────────────────────────
    if not vault_path or not vault_path.strip():
        return False

    vault_path = vault_path.strip()
    if not os.path.isdir(vault_path):
        logger.error("Obsidian vault path does not exist: %s", vault_path)
        return False

    # ── Ensure subdirectories ─────────────────────────────────────────
    crypto_dir = os.path.join(vault_path, CRYPTO_DIR)
    analysis_dir = os.path.join(crypto_dir, ANALYSIS_DIR)
    os.makedirs(crypto_dir, exist_ok=True)
    os.makedirs(analysis_dir, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Write markdown report ─────────────────────────────────────────
    md_path = os.path.join(crypto_dir, REPORT_FILE.format(pair=pair, date=date_str))
    try:
        md_content = _build_markdown_report(pair, scan_result, date_str)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info("Obsidian sync: wrote report %s", md_path)
    except OSError as exc:
        logger.error("Failed to write markdown report %s: %s", md_path, exc)
        return False

    # ── Save chart PNG ────────────────────────────────────────────────
    candles = scan_result.get("candles", [])
    if candles:
        chart_path = os.path.join(analysis_dir, CHART_FILE.format(pair=pair, date=date_str))
        try:
            df = _candles_to_dataframe(candles)
            if df is not None and not df.empty:
                mf_charts.render_mplfinance(
                    df,
                    title=f"{pair} Daily Chart",
                    save_path=chart_path,
                    bars=len(df),
                )
                logger.info("Obsidian sync: saved chart %s", chart_path)
        except Exception as exc:
            logger.warning("Obsidian sync: chart rendering failed for %s: %s", pair, exc)
            # Non-fatal — the report was written
    else:
        logger.warning(
            "Obsidian sync: no candle data for %s — chart skipped", pair
        )

    return True


def sync_daily_digest(
    user_id: int,
    digest_content: str,
    vault_path: str,
) -> bool:
    """Write *digest_content* as a daily digest markdown to *vault_path*.

    Returns ``True`` on success, ``False`` when the vault path doesn't exist
    or write fails.
    """
    if not vault_path or not vault_path.strip():
        return False

    vault_path = vault_path.strip()
    if not os.path.isdir(vault_path):
        logger.error("Obsidian vault path does not exist: %s", vault_path)
        return False

    crypto_dir = os.path.join(vault_path, CRYPTO_DIR)
    os.makedirs(crypto_dir, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md_path = os.path.join(crypto_dir, DIGEST_FILE.format(date=date_str))

    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(digest_content)
        logger.info("Obsidian sync: wrote daily digest %s", md_path)
        return True
    except OSError as exc:
        logger.error("Failed to write daily digest %s: %s", md_path, exc)
        return False


# ── Settings helpers (async, for use with AsyncSession) ────────────────────


async def get_vault_path(
    session,  # AsyncSession
    user_id: int,
) -> Optional[str]:
    """Return the Obsidian vault path for *user_id*, or ``None`` if not configured.

    Reads from ``PairSetting`` with pair ``__VAULT__``.
    """
    from sqlalchemy import select  # noqa: E402 (import guard)

    result = await session.execute(
        select(PairSetting).where(
            PairSetting.user_id == user_id,
            PairSetting.pair == VAULT_SETTINGS_PAIR,
        )
    )
    setting_row = result.scalar_one_or_none()
    if setting_row is not None and setting_row.settings:
        import json
        try:
            settings = json.loads(setting_row.settings) if isinstance(setting_row.settings, str) else setting_row.settings
            if isinstance(settings, dict):
                vault_path = settings.get("obsidian_vault_path", "").strip()
                return vault_path if vault_path else None
        except (json.JSONDecodeError, TypeError):
            pass
    return None


async def is_sync_enabled(
    session,  # AsyncSession
    user_id: int,
    pair: str,
) -> bool:
    """Check if Obsidian sync is enabled for this (user, pair).

    Default: ``True`` when the pair has no explicit setting.
    """
    from sqlalchemy import select  # noqa: E402

    result = await session.execute(
        select(PairSetting).where(
            PairSetting.user_id == user_id,
            PairSetting.pair == pair,
        )
    )
    setting_row = result.scalar_one_or_none()
    if setting_row is not None and setting_row.settings:
        import json
        try:
            settings = json.loads(setting_row.settings) if isinstance(setting_row.settings, str) else setting_row.settings
            if isinstance(settings, dict):
                return bool(settings.get("obsidian_sync", True))
        except (json.JSONDecodeError, TypeError):
            pass
    return True


# ── Internal helpers ──────────────────────────────────────────────────────


def _build_markdown_report(
    pair: str,
    result: dict[str, Any],
    date_str: str,
) -> str:
    """Build a full markdown report from the scan result dict."""
    lines: list[str] = []

    # ── Frontmatter ───────────────────────────────────────────────────
    lines.append("---")
    lines.append(f"symbol: {pair}")
    lines.append(f"date: {date_str}")
    lines.append("tags: [crypto, analysis]")
    lines.append("---")
    lines.append("")

    # ── Title ─────────────────────────────────────────────────────────
    lines.append(f"# {pair} Crypto Pair Analysis")
    lines.append("")
    lines.append(f"*Analysis date: {date_str}*")
    lines.append("")

    # ── Confluence Score ──────────────────────────────────────────────
    overall_score = result.get("overall_score")
    conf_score = result.get("confluence_score", 0)
    lines.append("## Confluence Score")
    lines.append("")
    if overall_score is not None:
        lines.append(f"- **Overall Score**: {overall_score}/100")
    lines.append(f"- **Confluence Score**: {conf_score}/30")
    lines.append("")

    # ── Score Breakdown ───────────────────────────────────────────────
    score_bd = result.get("score_breakdown", {})
    lines.append("## Score Breakdown")
    lines.append("")
    if isinstance(score_bd, dict) and "error" not in score_bd:
        for category in ("regime", "location", "confirmation", "volume_retest", "risk"):
            cat_data = score_bd.get(category)
            if isinstance(cat_data, dict):
                score_val = cat_data.get("score", "N/A")
                max_score = cat_data.get("max", "")
                label = category.replace("_", " ").title()
                if max_score:
                    lines.append(f"- **{label}**: {score_val}/{max_score}")
                else:
                    lines.append(f"- **{label}**: {score_val}")
        lines.append("")
        # Per-check breakdown
        lines.append("### Score Checks")
        lines.append("")
        checks: dict[str, list[str]] = {}
        for cat in ("regime", "location", "confirmation", "volume_retest", "risk"):
            cat_data = score_bd.get(cat)
            if isinstance(cat_data, dict):
                checks_list = cat_data.get("checks", {})
                if isinstance(checks_list, dict):
                    for check, passed in checks_list.items():
                        check_label = check.replace("_", " ").replace("-", " ").title()
                        icon = "✅" if passed else "❌"
                        checks.setdefault(category, []).append(
                            f"  - {icon} {check_label}: {'Yes' if passed else 'No'}"
                        )
        for cat, items in checks.items():
            cat_label = cat.replace("_", " ").title()
            lines.append(f"**{cat_label}**")
            lines.extend(items)
            lines.append("")
    else:
        lines.append("*Score breakdown not available.*")
        lines.append("")

    # ── Trade Plan ────────────────────────────────────────────────────
    tp = result.get("trade_plan", {})
    tp_flat = result.get("trade_plan_flat", {})
    lines.append("## Trade Plan")
    lines.append("")
    if tp.get("trade_decision"):
        lines.append(f"- **Decision**: TRADE")
        lines.append(f"- **Direction**: {tp.get('direction', 'N/A')}")
    else:
        lines.append(f"- **Decision**: NO TRADE")
        lines.append(f"- **Verdict**: {tp.get('verdict', tp.get('reasoning', 'N/A'))}")
    lines.append("")

    # Entry / Stop / Target levels
    if tp_flat:
        entry = tp_flat.get("entry")
        stop_loss = tp_flat.get("stop_loss")
        target_1 = tp_flat.get("target_1")
        target_2 = tp_flat.get("target_2")
        target_3 = tp_flat.get("target_3")

        lines.append("### Entry & Exit Levels")
        lines.append("")
        if entry:
            lines.append(f"- **Entry**: {entry}")
        if stop_loss:
            lines.append(f"- **Stop Loss**: {stop_loss}")
        if target_1:
            lines.append(f"- **Target 1**: {target_1}")
        if target_2:
            lines.append(f"- **Target 2**: {target_2}")
        if target_3:
            lines.append(f"- **Target 3**: {target_3}")
        lines.append("")

        rationale = tp_flat.get("rationale")
        if rationale:
            lines.append(f"**Rationale**: {rationale}")
            lines.append("")

        # ── RSI Three-Entry System ──
        if tp.get("rsi_entry_system"):
            rsi_sys = tp["rsi_entry_system"]
            lines.append("### RSI Three-Entry System")
            lines.append("")
            lines.append(f"- **Current RSI**: {rsi_sys.get('current_rsi', 'N/A')}")
            for entry in rsi_sys.get("entries", []):
                lines.append(f"- {entry['entry']}: {entry['trigger']} → {entry['position_size']}")
            lines.append("")

        # ── DCA Strategy ──
        if tp.get("dca_strategy"):
            lines.append("### DCA Strategy")
            lines.append("")
            for item in tp["dca_strategy"]:
                lines.append(f"- {item}")
            lines.append("")

        # ── Risk Management ──
        if tp.get("risk_management"):
            lines.append("### Risk Management")
            lines.append("")
            for rule in tp["risk_management"]:
                lines.append(f"- {rule}")
            lines.append("")

    # ── Indicators Summary ────────────────────────────────────────────────
    indicators = result.get("indicators", {})
    if indicators and isinstance(indicators, dict):
        lines.append("## Technical Indicators")
        lines.append("")
        lines.append("| Timeframe | RSI | BB Squeeze | Cross |")
        lines.append("|-----------|-----|------------|-------|")
        for tf_name in ("daily", "4h", "1h", "weekly", "15m"):
            tf_data = indicators.get(tf_name, {})
            if isinstance(tf_data, dict) and "error" not in tf_data:
                rsi = tf_data.get("rsi", "")
                cross = tf_data.get("golden_death_cross", "")
                bb = "Yes" if tf_data.get("bb_squeeze") else "No"
                lines.append(f"| {tf_name} | {rsi} | {bb} | {cross} |")
            elif isinstance(tf_data, dict) and "error" in tf_data:
                lines.append(f"| {tf_name} | error | error | error |")
        lines.append("")

    # ── QQE Signals ───────────────────────────────────────────────────
    qqe = result.get("qqe", {})
    if qqe and isinstance(qqe, dict):
        lines.append("## QQE Signals")
        lines.append("")
        lines.append("| Timeframe | Signal |")
        lines.append("|-----------|--------|")
        for tf_name in ("daily", "4h", "1h"):
            tf_data = qqe.get(tf_name, {})
            if isinstance(tf_data, dict):
                sig = tf_data.get("signal", "N/A")
                lines.append(f"| {tf_name} | {sig} |")
        lines.append("")

    # ── SMC Summary ───────────────────────────────────────────────────
    smc_data = result.get("smc", {})
    if isinstance(smc_data, dict) and "error" not in smc_data:
        lines.append("## Smart Money Concepts (SMC)")
        lines.append("")
        obs = smc_data.get("order_blocks", [])
        fvgs = smc_data.get("fvgs", [])
        lg = smc_data.get("liquidity_grabs", [])
        lines.append(f"- **Order Blocks**: {len(obs)}")
        lines.append(f"- **FVGs**: {len(fvgs)}")
        lines.append(f"- **Liquidity Grabs**: {len(lg)}")
        lines.append("")

    # ── Patterns ──────────────────────────────────────────────────────
    patterns = result.get("patterns", {})
    if isinstance(patterns, dict) and "error" not in patterns:
        detected = patterns.get("detected", [])
        if detected and isinstance(detected, list):
            lines.append("## Chart Patterns")
            lines.append("")
            for p in detected:
                name = p.get("name", "Unknown")
                confirmed = "✅ Confirmed" if p.get("confirmed") else "❌ Unconfirmed"
                lines.append(f"- **{name}** — {confirmed}")
            lines.append("")

    # ── Chart Image Reference ─────────────────────────────────────────
    date_str_no_fmt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append("## Chart")
    lines.append("")
    lines.append(f"![[{ANALYSIS_DIR}/{CHART_FILE.format(pair=pair, date=date_str_no_fmt)}]]")
    lines.append("")

    # ── Macro Context ─────────────────────────────────────────────────
    macro = result.get("macro_data", {})
    if macro and isinstance(macro, dict):
        lines.append("## Macro Context")
        lines.append("")
        btc_d = macro.get("btc_d")
        usdt_d = macro.get("usdt_d")
        dxy = macro.get("dxy")
        fg = macro.get("fear_greed")
        if btc_d is not None:
            lines.append(f"- **BTC Dominance**: {btc_d:.1f}%" if isinstance(btc_d, (int, float)) else f"- **BTC Dominance**: {btc_d}")
        if usdt_d is not None:
            lines.append(f"- **USDT Dominance**: {usdt_d:.2f}%" if isinstance(usdt_d, (int, float)) else f"- **USDT Dominance**: {usdt_d}")
        if dxy is not None:
            lines.append(f"- **DXY**: {dxy:.2f}" if isinstance(dxy, (int, float)) else f"- **DXY**: {dxy}")
        if isinstance(fg, dict):
            fg_val = fg.get("value")
            fg_label = fg.get("label", "")
            if fg_val is not None:
                lines.append(f"- **Fear & Greed**: {fg_val} — {fg_label}")
        lines.append("")

    return "\n".join(lines)


def _candles_to_dataframe(candles: list[dict]) -> Optional[pd.DataFrame]:
    """Convert a list of candle dicts to a DataFrame for mplfinance.

    Expected dict keys: ``date``, ``open``, ``high``, ``low``, ``close``, ``volume``.
    Returns ``None`` if the list is empty or unparseable.
    """
    if not candles:
        return None

    try:
        df = pd.DataFrame(candles)

        # Normalise column names — mplfinance expects Open/High/Low/Close/Volume
        col_map: dict[str, str] = {}
        for col in df.columns:
            col_lower = col.lower().strip()
            if col_lower == "date":
                col_map[col] = "Date"
            elif col_lower in ("open", "o"):
                col_map[col] = "Open"
            elif col_lower in ("high", "h"):
                col_map[col] = "High"
            elif col_lower in ("low", "l"):
                col_map[col] = "Low"
            elif col_lower in ("close", "c"):
                col_map[col] = "Close"
            elif col_lower in ("volume", "vol", "v"):
                col_map[col] = "Volume"

        df = df.rename(columns=col_map)

        # Set Date as index
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df.set_index("Date", inplace=True)

        # Ensure we have the required columns
        required = {"Open", "High", "Low", "Close"}
        if not required.issubset(df.columns):
            logger.warning(
                "Candle data missing required columns. Got: %s", list(df.columns)
            )
            return None

        # Sort by date ascending
        df = df.sort_index()

        return df
    except Exception as exc:
        logger.warning("Failed to convert candles to DataFrame: %s", exc)
        return None
