"""Phase 2A MEXC Alembic migration rehearsal tests."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
PRE_PHASE2A_REVISION = "a1b2c3d4e5f6"
PHASE2A_REVISION = "20260725_phase2a_mexc_sync"


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')")}


def _indexes(db_path: Path, table: str) -> dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        indexes = {}
        for row in conn.execute(f"PRAGMA index_list('{table}')"):
            name = row[1]
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()[0]
            indexes[name] = sql or ""
        return indexes


def test_phase2a_upgrade_backfills_indexes_and_downgrade_restores_schema(tmp_path):
    db_path = tmp_path / "phase2a_migration.db"

    before = _run_alembic(db_path, "upgrade", PRE_PHASE2A_REVISION)
    assert before.returncode == 0, before.stderr + before.stdout

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (username, email, hashed_password, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            ("phase2amigration", "phase2amigration@test.local", "hashed"),
        )
        user_id = conn.execute("SELECT id FROM users WHERE username='phase2amigration'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO position_history (
                user_id, exchange, symbol, side, size, entry_price, exit_price,
                pnl, pnl_percent, leverage, close_time, updated_at
            ) VALUES (?, 'mexc', 'BTC_USDT', 'long', 1.0, 100.0, 101.0, 12.34, 5.67, 10.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (user_id,),
        )
        conn.commit()

    upgrade = _run_alembic(db_path, "upgrade", PHASE2A_REVISION)
    assert upgrade.returncode == 0, upgrade.stderr + upgrade.stdout

    position_columns = _columns(db_path, "position_history")
    order_columns = _columns(db_path, "order_history")
    assert {
        "exchange_position_id",
        "reported_pnl",
        "reported_roi_pct",
        "source_state",
        "source_updated_at",
        "synced_at",
    }.issubset(position_columns)
    assert {"exchange_order_id", "source_updated_at", "synced_at"}.issubset(order_columns)
    assert _columns(db_path, "futures_account_snapshots") >= {"user_id", "exchange", "settlement_asset", "equity", "source_ts", "synced_at"}
    assert _columns(db_path, "exchange_sync_state") >= {"user_id", "exchange", "stream", "status", "cursor_json", "updated_at"}

    position_indexes = _indexes(db_path, "position_history")
    order_indexes = _indexes(db_path, "order_history")
    assert "uq_position_history_user_exchange_source_id" in position_indexes
    assert "WHERE exchange_position_id IS NOT NULL" in position_indexes["uq_position_history_user_exchange_source_id"]
    assert "uq_order_history_user_exchange_source_id" in order_indexes
    assert "WHERE exchange_order_id IS NOT NULL" in order_indexes["uq_order_history_user_exchange_source_id"]

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT reported_pnl, reported_roi_pct, exchange_position_id FROM position_history WHERE user_id=?",
            (user_id,),
        ).fetchone()
        assert row == (12.34, 5.67, None)
        conn.execute(
            """
            INSERT INTO futures_account_snapshots (
                user_id, exchange, settlement_asset, equity, source_ts, synced_at
            ) VALUES (?, 'mexc', 'USDT', 1000.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (user_id,),
        )
        conn.execute(
            """
            INSERT INTO exchange_sync_state (
                user_id, exchange, stream, status, rows_fetched_total, complete, updated_at
            ) VALUES (?, 'mexc', 'positions_history', 'fresh', 1, 1, CURRENT_TIMESTAMP)
            """,
            (user_id,),
        )
        conn.commit()

    downgrade = _run_alembic(db_path, "downgrade", PRE_PHASE2A_REVISION)
    assert downgrade.returncode == 0, downgrade.stderr + downgrade.stdout

    assert not _columns(db_path, "futures_account_snapshots")
    assert not _columns(db_path, "exchange_sync_state")
    assert "exchange_position_id" not in _columns(db_path, "position_history")
    assert "reported_pnl" not in _columns(db_path, "position_history")
    assert "exchange_order_id" not in _columns(db_path, "order_history")
