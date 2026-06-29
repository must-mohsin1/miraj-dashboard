"""
QA Phase 3 - Dynamic Testing

Tests are split:
  A) Synchronous (no DB, no asyncio) - message formatting, Obsidian I/O
  B) Asynchronous (DB + asyncio)     - alert manager, settings, API

Usage:
    cd /Users/mustcompanymohsin/projects/miraj-dashboard
    JWT_SECRET_KEY=dev-secret-change-in-production python _qa_p3_dynamic.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "dev-secret-change-in-production")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("OBSIDIAN_VAULT_PATH", "")

import matplotlib
matplotlib.use("Agg")

# ── Globals ───────────────────────────────────────────────────────────
PASS = 0
FAIL = 0
SKIP = 0
results: list[dict[str, Any]] = []


def p(name: str):
    global PASS; PASS += 1
    results.append({"name": name, "status": "PASS"})
    print(f"  \u2713 {name}")


def f(name: str, detail: str = ""):
    global FAIL; FAIL += 1
    results.append({"name": name, "status": "FAIL", "detail": detail})
    print(f"  \u2717 {name}: {detail}"[:200])


def s(name: str, reason: str = ""):
    global SKIP; SKIP += 1
    results.append({"name": name, "status": "SKIP", "detail": reason})
    print(f"  \u2013 {name}: {reason}")


# ═══════════════════════════════════════════════════════════════════════
# PART A — SYNC TESTS (no DB)
# ═══════════════════════════════════════════════════════════════════════

def a1_telegram_full():
    """Telegram message has all required fields in correct format."""
    from backend.alerts.telegram import format_alert_message
    msg = format_alert_message(symbol="BTC-USD", score=85.5, direction="LONG",
                                entry=65000.0, stop_loss=64000.0, target=68000.0,
                                rationale="Strong bullish confluence")
    checks = [
        ("BTC-USD" in msg, "Symbol missing"),
        ("85.5" in msg, "Score missing"),
        ("LONG" in msg, "Direction missing"),
        ("65000.0" in msg, "Entry missing"),
        ("64000.0" in msg, "Stop loss missing"),
        ("68000.0" in msg, "Target missing"),
        ("Strong bullish confluence" in msg, "Rationale missing"),
        ("\U0001f3f7\ufe0f" in msg, "Flag emoji missing"),
        ("\u2b50" in msg, "Star emoji missing"),
        ("\U0001f4ca" in msg, "Chart emoji missing"),
    ]
    for ok, msg_ in checks:
        assert ok, msg_


def a2_telegram_minimal():
    """Minimal message (only required fields)."""
    from backend.alerts.telegram import format_alert_message
    msg = format_alert_message(symbol="ETH-USD", score=70.0, direction="SHORT")
    assert "ETH-USD" in msg
    assert "70.0" in msg
    assert "SHORT" in msg


def a3_discord_full():
    """Discord embed has correct title, colour, fields."""
    from backend.alerts.discord import build_embed
    embed = build_embed(symbol="BTC-USD", score=85.5, direction="LONG",
                         entry=65000.0, stop_loss=64000.0, target=68000.0, rationale="Test")
    assert embed["title"] == "Trade Alert: BTC-USD"
    assert embed["color"] == 0x00FF00  # GREEN for LONG
    assert "timestamp" in embed
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert "\U0001f3f7\ufe0f Symbol" in fields


def a4_discord_short_red():
    """SHORT direction produces RED colour."""
    from backend.alerts.discord import build_embed
    embed = build_embed(symbol="ETH-USD", score=30.0, direction="SHORT")
    assert embed["color"] == 0xFF0000  # RED for SHORT


def a5_digest_empty():
    """Empty digest = 'No scans run today'."""
    from backend.alerts.digest import build_digest_message
    msg = build_digest_message([])
    assert "No scans run today" in msg


def a6_digest_with_data():
    """Digest includes symbol, score, direction, highest TF, and actionable tag.
    
    Note: symbols are MarkdownV2-escaped (hyphens become \- etc.)
    """
    from backend.alerts.digest import build_digest_message
    rows = [
        {"symbol": "BTC-USD", "confluence_score": 85.0, "direction": "LONG",
         "highest_tf": "WEEKLY", "actionable": True},
        {"symbol": "ETH-USD", "confluence_score": 45.0, "direction": "SHORT",
         "highest_tf": "4H", "actionable": False},
    ]
    msg = build_digest_message(rows)
    # Symbols get MarkdownV2 escaped (hyphen -> \-)
    assert "BTC\\-USD" in msg or "BTC-USD" in msg, "BTC-USD symbol missing from digest"
    assert "ETH\\-USD" in msg or "ETH-USD" in msg, "ETH-USD symbol missing"
    assert "WEEKLY" in msg, "Highest timeframe missing"
    assert "ACTIONABLE" in msg, "Actionable tag missing"


def a7_digest_summary():
    """Summary counts are correct."""
    from backend.alerts.digest import build_digest_message
    rows = [
        {"symbol": "A", "confluence_score": 80.0, "direction": "LONG",
         "highest_tf": "DAILY", "actionable": True},
        {"symbol": "B", "confluence_score": 20.0, "direction": "SHORT",
         "highest_tf": "15M", "actionable": False},
    ]
    msg = build_digest_message(rows)
    assert "2 pairs" in msg
    assert "High-confluence" in msg
    assert "Actionable setups: 1" in msg


def a8_extract_highest_tf():
    """_extract_highest_tf returns correct TF hierarchy."""
    from backend.alerts.digest import _extract_highest_tf
    # Weekly > Daily > 4H > 15M
    assert _extract_highest_tf({
        "regime": {"breakdown": {"weekly_structure": True}},
        "confirmation": {"breakdown": {"h4_structure": True}},
    }) == "WEEKLY"
    assert _extract_highest_tf({
        "regime": {"breakdown": {"daily_structure": True}},
        "confirmation": {"breakdown": {"m15_structure": True}},
    }) == "DAILY"
    assert _extract_highest_tf({
        "regime": {"breakdown": {}},
        "confirmation": {"breakdown": {"h4_structure": True}},
    }) == "4H"
    assert _extract_highest_tf({
        "regime": {"breakdown": {}},
        "confirmation": {"breakdown": {"m15_structure": True}},
    }) == "15M"
    assert _extract_highest_tf({"regime": {"breakdown": {}}, "confirmation": {"breakdown": {}}}) is None
    assert _extract_highest_tf(None) is None


def a9_obsidian_invalid_path():
    """Sync to nonexistent path returns False."""
    from backend.obsidian import sync_scan_result
    assert sync_scan_result(user_id=1, pair="X", scan_result={}, vault_path="/nope") is False


def a10_obsidian_empty_path():
    """Sync with empty path returns False."""
    from backend.obsidian import sync_scan_result
    assert sync_scan_result(user_id=1, pair="X", scan_result={}, vault_path="") is False


def a11_obsidian_writes_files():
    """Sync writes .md report file to vault."""
    from backend.obsidian import sync_scan_result
    vault = tempfile.mkdtemp(prefix="qa_obs_")
    try:
        r = sync_scan_result(1, "BTCUSDT", _sample(), vault)
        assert r is True
        crypto = os.path.join(vault, "crypto")
        mds = [f for f in os.listdir(crypto) if f.endswith(".md")]
        assert len(mds) >= 1, f"No .md in {crypto}"
        with open(os.path.join(crypto, mds[0])) as fh:
            c = fh.read()
        assert "# BTCUSDT Crypto Pair Analysis" in c
    finally:
        import shutil; shutil.rmtree(vault, ignore_errors=True)


def a12_obsidian_chart_skipped():
    """No candle data => chart skipped, report still written."""
    from backend.obsidian import sync_scan_result
    vault = tempfile.mkdtemp(prefix="qa_obs_")
    s = _sample()
    s["candles"] = []
    try:
        r = sync_scan_result(1, "ETHUSDT", s, vault)
        assert r is True
        crypto = os.path.join(vault, "crypto")
        mds = [f for f in os.listdir(crypto) if f.endswith(".md")]
        assert len(mds) >= 1
        analysis = os.path.join(crypto, "analysis")
        if os.path.isdir(analysis):
            assert len([f for f in os.listdir(analysis) if f.endswith(".png")]) == 0
    finally:
        import shutil; shutil.rmtree(vault, ignore_errors=True)


def a13_obsidian_daily_digest():
    """Daily digest sync writes to vault."""
    from backend.obsidian import sync_daily_digest
    vault = tempfile.mkdtemp(prefix="qa_obs_")
    try:
        r = sync_daily_digest(1, "# Daily Digest\n\nContent", vault)
        assert r is True
        dfs = [f for f in os.listdir(os.path.join(vault, "crypto")) if f.startswith("daily_digest_")]
        assert len(dfs) >= 1
    finally:
        import shutil; shutil.rmtree(vault, ignore_errors=True)


def _sample() -> dict:
    return {
        "symbol": "BTCUSDT", "overall_score": 72.5, "confluence_score": 18.0,
        "score_breakdown": {
            "regime": {"score": 5.0, "max": 8.0, "checks": {}},
            "location": {"score": 4.0, "max": 6.0, "checks": {}},
            "confirmation": {"score": 5.0, "max": 8.0, "checks": {}},
            "volume_retest": {"score": 2.0, "max": 4.0, "checks": {}},
            "risk": {"score": 2.0, "max": 4.0, "checks": {}},
        },
        "trade_plan": {"trade_decision": True, "direction": "LONG", "reasoning": "bullish"},
        "trade_plan_flat": {"direction": "LONG", "entry": 68500.0, "stop_loss": 67200.0,
                            "target_1": 69800.0},
        "candles": [
            {"date": "2026-06-14", "open": 67000, "high": 67500, "low": 66800, "close": 67200, "volume": 10000},
            {"date": "2026-06-15", "open": 67200, "high": 67800, "low": 67000, "close": 67600, "volume": 11000},
        ],
    }


def run_sync_tests():
    tests = [
        ("Telegram format - full", a1_telegram_full),
        ("Telegram format - minimal", a2_telegram_minimal),
        ("Discord embed - full", a3_discord_full),
        ("Discord embed - SHORT=red", a4_discord_short_red),
        ("Digest - empty day", a5_digest_empty),
        ("Digest - with data", a6_digest_with_data),
        ("Digest - summary counts", a7_digest_summary),
        ("_extract_highest_tf helper", a8_extract_highest_tf),
        ("Obsidian - invalid path", a9_obsidian_invalid_path),
        ("Obsidian - empty path", a10_obsidian_empty_path),
        ("Obsidian - writes .md report", a11_obsidian_writes_files),
        ("Obsidian - no candles", a12_obsidian_chart_skipped),
        ("Obsidian - daily digest sync", a13_obsidian_daily_digest),
    ]
    for name, fn in tests:
        try:
            fn(); p(name)
        except AssertionError as e:
            f(name, str(e) or "Assertion failed")
        except Exception as e:
            f(name, f"{type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# PART B — ASYNC TESTS (single event loop, each _init_db_async + _create_tables)
# ═══════════════════════════════════════════════════════════════════════

_engine_global = None


def _init_db_async():
    """Set up fresh DB path + engine, no tables yet."""
    global _engine_global
    from backend import database
    db_path = os.path.join(PROJECT_ROOT, "_qa_test.db")
    if os.path.exists(db_path):
        os.unlink(db_path)
    for attr in ("_DB_PATH", "_engine", "_session_factory"):
        setattr(database, attr, None)
    database.set_db_path(db_path)
    _engine_global = database.get_engine()


async def _create_tables():
    from backend.database import Base
    async with _engine_global.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _make_user(session):
    from backend.auth import hash_password, create_access_token
    from backend.models import User
    u = User(username="qat", email="q@t.com", hashed_password=hash_password("x"))
    session.add(u)
    await session.flush()
    await session.refresh(u)
    return u, create_access_token(data={"sub": str(u.id)})


async def _user_ch(session):
    from backend.models import AlertChannel
    u, t = await _make_user(session)
    session.add(AlertChannel(user_id=u.id, channel_type="telegram",
                             config=json.dumps({"chat_id": "12345"}), enabled=1))
    await session.flush()
    return u, t


def _sr(sym: str, sc: float, d: str = "LONG") -> dict:
    return dict(symbol=sym, confluence_score=sc, overall_score=sc,
                trade_plan={"trade_decision": True, "direction": d},
                score_breakdown={"total": sc})


async def run_async_tests():
    from backend.database import get_session_factory
    from backend.models import AlertChannel, AlertHistory, PairSetting
    from backend.alerts.manager import DEFAULT_COOLDOWN_HOURS, process_scan_results
    from sqlalchemy import select

    # ── b1: threshold filtering ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _user_ch(s)
        s.add(PairSetting(user_id=u.id, pair="BTC-USD", settings=json.dumps({"alert_threshold": 70})))
        await s.flush()
        # 50 < 70 -> no alert
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("BTC-USD", 50.0)]})
        m.assert_not_called(); assert os_ == []
        # 85 > 70 -> alert
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("BTC-USD", 85.0)]})
        m.assert_awaited_once(); assert os_[0]["status"] == "sent"
    p("Threshold - below fails, above sends alert")

    # ── b2: default threshold ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _user_ch(s)
        # 50 < default 60 -> no
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("BTC-USD", 50.0)]})
        m.assert_not_called(); assert os_ == []
        # 65 > 60 -> yes
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("ETH-USD", 65.0)]})
        m.assert_awaited_once()
    p("Default threshold (60) - below no alert, above sends")

    # ── b3: dedup within cooldown ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _user_ch(s)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_COOLDOWN_HOURS - 1)
        s.add(AlertHistory(user_id=u.id, pair="BTC-USD", channel="telegram", score=75,
                           direction="LONG", message="Sent", status="sent", created_at=cutoff))
        await s.flush()
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("BTC-USD", 80.0)]})
        m.assert_not_called(); assert os_ == []
    p("Dedup - within cooldown (no alert)")

    # ── b4: dedup after cooldown ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _user_ch(s)
        old = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_COOLDOWN_HOURS + 1)
        s.add(AlertHistory(user_id=u.id, pair="BTC-USD", channel="telegram", score=75,
                           direction="LONG", message="Sent", status="sent", created_at=old))
        await s.flush()
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("BTC-USD", 80.0)]})
        m.assert_awaited_once(); assert len(os_) == 1
    p("Dedup - after cooldown (alert sent)")

    # ── b5: multi-channel ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _make_user(s)
        s.add(AlertChannel(user_id=u.id, channel_type="telegram",
                           config=json.dumps({"chat_id": "12345"}), enabled=1))
        s.add(AlertChannel(user_id=u.id, channel_type="discord",
                           config=json.dumps({"webhook_url": "https://discord.com/api/webhooks/t"}), enabled=1))
        await s.flush()
        r = _sr("BTC-USD", 85.0); r["trade_plan"]["entry"] = 100.0
        with (
            patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as mt,
            patch("backend.alerts.manager.send_webhook", new_callable=AsyncMock, return_value=True) as md,
        ):
            os_ = await process_scan_results(s, {u.id: [r]})
        mt.assert_awaited_once(); md.assert_awaited_once()
        assert set(os_[0]["channels_sent"]) == {"telegram", "discord"}
    p("Multi-channel routing (Telegram + Discord)")

    # ── b6: disabled channel ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _make_user(s)
        s.add(AlertChannel(user_id=u.id, channel_type="telegram",
                           config=json.dumps({"chat_id": "12345"}), enabled=0))
        await s.flush()
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("BTC-USD", 85.0)]})
        m.assert_not_called(); assert os_ == []
    p("Disabled channel skipped")

    # ── b7: history logging ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _user_ch(s)
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True):
            await process_scan_results(s, {u.id: [_sr("BTC-USD", 80.0)]})
        rows = (await s.execute(select(AlertHistory).where(AlertHistory.user_id == u.id))).scalars().all()
        assert len(rows) == 1
        assert rows[0].pair == "BTC-USD" and rows[0].status == "sent"
    p("Alert history logged for sent alerts")

    # ── b8: settings persistence ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _make_user(s)
        s.add(PairSetting(user_id=u.id, pair="BTC-USD",
                          settings=json.dumps({"alert_threshold": 15, "alert_enabled": True})))
        await s.flush()
        r = (await s.execute(select(PairSetting).where(PairSetting.user_id == u.id, PairSetting.pair == "BTC-USD"))).scalar_one()
        assert json.loads(r.settings)["alert_threshold"] == 15
        js = json.loads(r.settings); js["alert_threshold"] = 25; r.settings = json.dumps(js)
        await s.flush()
        r2 = (await s.execute(select(PairSetting).where(PairSetting.user_id == u.id, PairSetting.pair == "BTC-USD"))).scalar_one()
        assert json.loads(r2.settings)["alert_threshold"] == 25
    p("Settings CRUD - save then reload")

    # ── b9: per-pair threshold change ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _user_ch(s)
        ps = PairSetting(user_id=u.id, pair="BTC-USD", settings=json.dumps({"alert_threshold": 10}))
        s.add(ps); await s.flush()
        # threshold 10, score 12 -> alert (BTC-USD threshold=10, 12>=10)
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("BTC-USD", 12.0)]})
        m.assert_awaited_once()
        # change BTC-USD threshold to 15
        ps.settings = json.dumps({"alert_threshold": 15}); await s.flush()
        # BTC-USD 12 < 15 -> no alert (also cooldown, but threshold check comes first)
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("BTC-USD", 12.0)]})
        m.assert_not_called(); assert os_ == [], f"Expected no outcomes, got {os_}"
        # Also set ETH-USD threshold to 15 so score 18 passes
        s.add(PairSetting(user_id=u.id, pair="ETH-USD", settings=json.dumps({"alert_threshold": 15})))
        await s.flush()
        # ETH-USD 18 > 15 -> alert
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as m:
            os_ = await process_scan_results(s, {u.id: [_sr("ETH-USD", 18.0)]})
        m.assert_awaited_once()
    p("Threshold change (10 -> 15 -> filter 12/18)")

    # ── b10: alert_enabled=False (BUG DETECTION) ──
    _init_db_async(); factory = get_session_factory()
    async with factory() as s:
        await _create_tables()
        u, t = await _user_ch(s)
        s.add(PairSetting(user_id=u.id, pair="BTC-USD",
                          settings=json.dumps({"alert_enabled": False, "alert_threshold": 0})))
        await s.flush()
        with patch("backend.alerts.manager.send_alert", new_callable=AsyncMock, return_value=True) as m:
            outcomes = await process_scan_results(s, {u.id: [_sr("BTC-USD", 99.0)]})
        if len(outcomes) > 0:
            f("alert_enabled=False flag",
              "BUG: alert_enabled=False is never checked by manager.py "
              "_process_single_result. Toggling alert off has NO EFFECT.")
        else:
            p("alert_enabled=False respected")
    p("alert_enabled=False check completed")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("QA Phase 3 \u2014 Dynamic Testing")
    print("=" * 60)
    print()

    print("--- Sync tests ---")
    run_sync_tests()

    print()
    print("--- Async tests ---")
    asyncio.run(run_async_tests())

    # Summary
    print()
    print("=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed, {SKIP} skipped")
    print("=" * 60)

    fails = [r for r in results if r["status"] == "FAIL"]
    if fails:
        print()
        print("FAILED:")
        for r in fails:
            print(f"  \u2717 {r['name']}")
            if r.get("detail"):
                print(f"      {r['detail']}")

    # Check for known bug
    if any("BUG" in (r.get("detail") or "") for r in fails):
        print()
        print("BUG FOUND: alert_enabled=False is defined in PairSetting but")
        print("  manager.py _process_single_result never checks it.")
        print("  Toggling alert OFF for a pair has NO EFFECT.")
        print("  Fix: add an alert_enabled check before sending.")

    print()
    if FAIL > 0:
        print("VERDICT: ISSUES FOUND \u2014 see report")
        print("Ship-readiness: NOT SHIPPABLE")
    else:
        print("VERDICT: All tests pass")
        print("Ship-readiness: SHIPPABLE")

    # Cleanup
    try: os.unlink("_qa_test.db")
    except OSError: pass
