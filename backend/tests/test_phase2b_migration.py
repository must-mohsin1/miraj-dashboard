"""Phase 2B capital-flow ledger Alembic migration tests."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
PRE_PHASE2B_REVISION = "20260725_phase2a_mexc_sync"
PHASE2B_REVISION = "20260804_phase2b_capital_flow"


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
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            ).fetchone()
            indexes[name] = (sql[0] if sql else "") or ""
        return indexes


def test_phase2b_upgrade_creates_ledger_indexes_and_downgrade_drops_table(tmp_path):
    db_path = tmp_path / "phase2b_migration.db"

    before = _run_alembic(db_path, "upgrade", PRE_PHASE2B_REVISION)
    assert before.returncode == 0, before.stderr + before.stdout
    assert not _columns(db_path, "capital_flow_ledger")

    upgrade = _run_alembic(db_path, "upgrade", PHASE2B_REVISION)
    assert upgrade.returncode == 0, upgrade.stderr + upgrade.stdout

    cols = _columns(db_path, "capital_flow_ledger")
    assert {
        "id",
        "user_id",
        "exchange",
        "entry_type",
        "exchange_entry_id",
        "asset",
        "amount",
        "signed_amount",
        "status",
        "occurred_at",
        "source_updated_at",
        "synced_at",
        "raw_json",
    }.issubset(cols)

    indexes = _indexes(db_path, "capital_flow_ledger")
    assert "uq_capital_flow_user_exchange_type_source_id" in indexes
    assert "WHERE exchange_entry_id IS NOT NULL" in indexes["uq_capital_flow_user_exchange_type_source_id"]
    assert "ix_capital_flow_user_exchange_occurred" in indexes

    downgrade = _run_alembic(db_path, "downgrade", PRE_PHASE2B_REVISION)
    assert downgrade.returncode == 0, downgrade.stderr + downgrade.stdout
    assert not _columns(db_path, "capital_flow_ledger")
