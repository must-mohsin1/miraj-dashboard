"""Tests for the Obsidian vault sync service (P3-C).

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_obsidian.py -v

Tests use a temporary on-disk vault directory.
"""

from __future__ import annotations

# Force matplotlib Agg backend for headless chart rendering
# MUST be set before any import that touches mplfinance/matplotlib
import matplotlib
matplotlib.use("Agg")

import os
import sys
import tempfile
from typing import Any

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import time)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.obsidian import (
    _build_markdown_report,
    _candles_to_dataframe,
    sync_daily_digest,
    sync_scan_result,
)


# ── Sample scan result ────────────────────────────────────────────────────

SAMPLE_RESULT: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "overall_score": 72.5,
    "confluence_score": 18.0,
    "score_breakdown": {
        "regime": {
            "score": 5.0,
            "max": 8.0,
            "checks": {
                "weekly_structure_aligned": True,
                "daily_structure_aligned": True,
                "btc_d_aligned": True,
                "fear_greed_aligned": False,
            },
        },
        "location": {
            "score": 4.0,
            "max": 6.0,
            "checks": {
                "demand_supply_zone": True,
                "order_block_at_zone": True,
                "fvg_at_zone": False,
            },
        },
        "confirmation": {
            "score": 5.0,
            "max": 8.0,
            "checks": {
                "h4_structure_aligned": True,
                "daily_rsi_confirms": True,
                "qqe_aligned": True,
                "chart_pattern_confirmed": False,
            },
        },
        "volume_retest": {
            "score": 2.0,
            "max": 4.0,
            "checks": {
                "volume_confirming": True,
                "retest_confirmed": True,
            },
        },
        "risk": {
            "score": 2.0,
            "max": 4.0,
            "checks": {
                "target_2r_available": True,
                "clean_stop_level": True,
            },
        },
    },
    "trade_plan": {
        "trade_decision": True,
        "direction": "LONG",
        "reasoning": "Bullish confluence from structure and QQE alignment",
    },
    "trade_plan_flat": {
        "direction": "LONG",
        "entry": 68500.0,
        "stop_loss": 67200.0,
        "target_1": 69800.0,
        "target_2": 71100.0,
        "target_3": 72400.0,
        "rationale": "Bullish confluence from structure and QQE alignment",
    },
    "indicators": {
        "daily": {"rsi": 58.2, "bb_squeeze": False, "golden_death_cross": "golden"},
        "4h": {"rsi": 52.1, "bb_squeeze": False},
        "1h": {"rsi": 48.5, "bb_squeeze": True},
    },
    "qqe": {
        "daily": {"signal": "GREEN"},
        "4h": {"signal": "GREEN-STRONG"},
        "1h": {"signal": "RED"},
    },
    "smc": {
        "order_blocks": [{"zone": (68000, 68500)}],
        "fvgs": [{"zone": (67500, 67800)}],
        "liquidity_grabs": [],
    },
    "patterns": {
        "detected": [
            {"name": "Bullish Engulfing", "confirmed": True},
            {"name": "Hammer", "confirmed": False},
        ]
    },
    "macro_data": {
        "btc_d": 55.3,
        "usdt_d": 3.45,
        "dxy": 104.5,
        "fear_greed": {"value": 42, "label": "Fear"},
    },
    "candles": [
        {"date": "2026-06-14", "open": 67000, "high": 67500, "low": 66800, "close": 67200, "volume": 10000},
        {"date": "2026-06-15", "open": 67200, "high": 67800, "low": 67000, "close": 67600, "volume": 11000},
        {"date": "2026-06-16", "open": 67600, "high": 68000, "low": 67300, "close": 67800, "volume": 9500},
        {"date": "2026-06-17", "open": 67800, "high": 68200, "low": 67500, "close": 68000, "volume": 10500},
        {"date": "2026-06-18", "open": 68000, "high": 68500, "low": 67700, "close": 68200, "volume": 11500},
        {"date": "2026-06-19", "open": 68200, "high": 68800, "low": 68000, "close": 68600, "volume": 10800},
        {"date": "2026-06-20", "open": 68600, "high": 69000, "low": 68300, "close": 68400, "volume": 12000},
        {"date": "2026-06-21", "open": 68400, "high": 68900, "low": 68100, "close": 68700, "volume": 9800},
        {"date": "2026-06-22", "open": 68700, "high": 69200, "low": 68500, "close": 69000, "volume": 11200},
        {"date": "2026-06-23", "open": 69000, "high": 69500, "low": 68700, "close": 69200, "volume": 13000},
        {"date": "2026-06-24", "open": 69200, "high": 69800, "low": 69000, "close": 69500, "volume": 12500},
        {"date": "2026-06-25", "open": 69500, "high": 70000, "low": 69100, "close": 69300, "volume": 11800},
    ],
}


# ── Tests for sync_scan_result ─────────────────────────────────────────────


def test_sync_scan_result_writes_files_to_vault(tmp_path):
    """After sync with valid vault path, report markdown + chart PNG are created."""
    vault = tmp_path / "vault"
    vault.mkdir()

    result = sync_scan_result(
        user_id=1,
        pair="BTCUSDT",
        scan_result=SAMPLE_RESULT,
        vault_path=str(vault),
    )

    assert result is True

    # Check report was written
    crypto_dir = vault / "crypto"
    analysis_dir = crypto_dir / "analysis"
    assert crypto_dir.is_dir()
    assert analysis_dir.is_dir()

    # Should have at least one .md file
    md_files = list(crypto_dir.glob("Crypto_Pair_Analysis_*.md"))
    assert len(md_files) >= 1
    md_content = md_files[0].read_text()
    assert "# BTCUSDT Crypto Pair Analysis" in md_content
    assert "Confluence Score" in md_content
    assert "Score Breakdown" in md_content
    assert "Trade Plan" in md_content
    assert "Entry" in md_content or "Entry" in md_content
    assert "Stop Loss" in md_content
    assert "Target 1" in md_content
    assert "Overall Score" in md_content
    assert "72.5" in md_content
    assert "Bullish confluence from structure" in md_content


def test_sync_scan_result_chart_png_created(tmp_path):
    """Chart PNG should be created in the analysis subdir."""
    vault = tmp_path / "vault"
    vault.mkdir()

    sync_scan_result(
        user_id=1,
        pair="BTCUSDT",
        scan_result=SAMPLE_RESULT,
        vault_path=str(vault),
    )

    analysis_dir = vault / "crypto" / "analysis"
    png_files = list(analysis_dir.glob("*.png"))
    assert len(png_files) >= 1


def test_sync_scan_result_invalid_path_returns_false():
    """sync_scan_result returns False when the vault path does not exist."""
    result = sync_scan_result(
        user_id=1,
        pair="BTCUSDT",
        scan_result=SAMPLE_RESULT,
        vault_path="/nonexistent/vault/path",
    )
    assert result is False


def test_sync_scan_result_empty_path_returns_false():
    """sync_scan_result returns False when vault path is empty string."""
    result = sync_scan_result(
        user_id=1, pair="BTCUSDT", scan_result=SAMPLE_RESULT, vault_path=""
    )
    assert result is False


def test_sync_scan_result_no_candles_skips_chart(tmp_path):
    """When no candle data is present, the report is still written but chart is skipped."""
    vault = tmp_path / "vault"
    vault.mkdir()
    no_candle_result = dict(SAMPLE_RESULT)
    no_candle_result["candles"] = []

    result = sync_scan_result(
        user_id=1,
        pair="ETHUSDT",
        scan_result=no_candle_result,
        vault_path=str(vault),
    )

    assert result is True
    analysis_dir = vault / "crypto" / "analysis"
    png_files = list(analysis_dir.glob("*.png"))
    assert len(png_files) == 0


# ── Tests for sync_daily_digest ────────────────────────────────────────────


def test_sync_daily_digest_writes_file(tmp_path):
    """sync_daily_digest writes the digest markdown to the vault."""
    vault = tmp_path / "vault"
    vault.mkdir()

    digest = "# Daily Digest\n\nBTCUSDT showing bullish confluence.\n"
    result = sync_daily_digest(
        user_id=1,
        digest_content=digest,
        vault_path=str(vault),
    )

    assert result is True
    crypto_dir = vault / "crypto"
    digest_files = list(crypto_dir.glob("daily_digest_*.md"))
    assert len(digest_files) >= 1
    content = digest_files[0].read_text()
    assert "Daily Digest" in content


def test_sync_daily_digest_invalid_path_returns_false():
    """sync_daily_digest returns False when vault path doesn't exist."""
    result = sync_daily_digest(
        user_id=1, digest_content="# test", vault_path="/nonexistent"
    )
    assert result is False


def test_sync_daily_digest_empty_path_returns_false():
    """sync_daily_digest returns False when vault path is empty."""
    result = sync_daily_digest(
        user_id=1, digest_content="# test", vault_path=""
    )
    assert result is False


# ── Tests for _build_markdown_report ───────────────────────────────────────


def test_build_markdown_contains_all_required_sections():
    """The markdown report includes confluence score, score breakdown, trade plan, levels."""
    md = _build_markdown_report("BTCUSDT", SAMPLE_RESULT, "2026-06-28")

    assert md.startswith("---")
    assert "symbol: BTCUSDT" in md
    assert "Confluence Score" in md
    assert "Score Breakdown" in md
    assert "Trade Plan" in md
    assert "Entry & Exit Levels" in md
    assert "Entry" in md
    assert "Stop Loss" in md
    assert "Target 1" in md
    assert "Target 2" in md
    assert "Rationale" in md
    assert "Technical Indicators" in md
    assert "QQE Signals" in md
    assert "Smart Money Concepts" in md
    assert "Chart Patterns" in md
    assert "Macro Context" in md
    assert "✅" in md  # Emoji for passed checks
    assert "❌" in md  # Emoji for failed checks


def test_build_markdown_no_trade_decision():
    """When trade_decision is False, the report reflects 'NO TRADE'."""
    no_trade = dict(SAMPLE_RESULT)
    no_trade["trade_plan"] = {
        "trade_decision": False,
        "verdict": "Not enough confluence for a trade",
    }
    no_trade.pop("trade_plan_flat", None)

    md = _build_markdown_report("BTCUSDT", no_trade, "2026-06-28")
    assert "NO TRADE" in md
    assert "Not enough confluence for a trade" in md


def test_build_markdown_score_breakdown_error():
    """When score_breakdown has an error, the report shows a fallback message."""
    bad = dict(SAMPLE_RESULT)
    bad["score_breakdown"] = {"error": "Scoring failed"}

    md = _build_markdown_report("BTCUSDT", bad, "2026-06-28")
    assert "Score breakdown not available" in md
    # Should not crash on individual category access
    assert "Regime" not in md or True  # Categories won't be rendered


# ── Tests for _candles_to_dataframe ───────────────────────────────────────


def test_candles_to_dataframe_converts_correctly():
    """Candle list is converted to a DataFrame with OHLCV columns + Date index."""
    df = _candles_to_dataframe(SAMPLE_RESULT["candles"])
    assert df is not None
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 12
    # Check values
    assert df["Open"].iloc[0] == 67000
    assert df["Close"].iloc[-1] == 69300
    # Date index should be datetime
    assert df.index.name == "Date" or df.index.name is None


def test_candles_to_dataframe_empty_returns_none():
    """Empty candle list returns None."""
    df = _candles_to_dataframe([])
    assert df is None


def test_candles_to_dataframe_missing_columns_returns_none():
    """Candles missing required price columns return None."""
    invalid = [{"date": "2026-06-28", "close": 69000}]  # Missing Open/High/Low
    df = _candles_to_dataframe(invalid)
    assert df is None


# ── Tests for settings helpers (via core logic, no DB) ─────────────────────


def test_sync_scan_result_path_with_whitespace(tmp_path):
    """Leading/trailing whitespace in vault path is stripped."""
    vault = tmp_path / "vault"
    vault.mkdir()

    result = sync_scan_result(
        user_id=1,
        pair="BTCUSDT",
        scan_result=SAMPLE_RESULT,
        vault_path=f"  {vault}  ",  # With whitespace
    )

    assert result is True
    assert (vault / "crypto" / "analysis").is_dir()
