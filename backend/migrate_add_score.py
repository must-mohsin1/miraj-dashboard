"""
Migration: Add ``score`` column to the ``analyses`` table and backfill it.

Usage
-----
    python -m backend.migrate_add_score          # uses default DB path (crypto_analysis.db)
    DATABASE_URL=test_scan.db python -m backend.migrate_add_score

This:
  1. Adds the ``score`` FLOAT column if it does not already exist.
  2. Backfills existing rows by extracting the score from the ``result`` JSON
     (looking for ``overall_score`` or ``confluence_score``).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def get_db_path() -> str:
    return os.environ.get(
        "DATABASE_URL",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "crypto_analysis.db"),
    )


def _extract_score(result_str: str | None) -> float | None:
    """Extract the score from a JSON result blob (same logic as history._parse_result)."""
    if not result_str:
        return None
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return None
    score: float | None = data.get("overall_score") or data.get("confluence_score")
    return score


def migrate() -> int:
    """Run the migration. Returns the number of rows backfilled."""
    db_path = get_db_path()
    logger.info("Connecting to %s", db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ── Step 1: Add column if missing ──────────────────────────────
    cursor.execute("PRAGMA table_info(analyses)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "score" not in columns:
        logger.info("Adding `score` FLOAT column to analyses table …")
        cursor.execute("ALTER TABLE analyses ADD COLUMN score FLOAT")
        conn.commit()
    else:
        logger.info("`score` column already exists; skipping ALTER TABLE.")

    # ── Step 2: Backfill existing rows ─────────────────────────────
    cursor.execute(
        "SELECT id, result FROM analyses WHERE score IS NULL AND result IS NOT NULL"
    )
    rows = cursor.fetchall()
    if not rows:
        logger.info("No rows to backfill.")
        conn.close()
        return 0

    backfilled = 0
    for row in rows:
        score = _extract_score(row["result"])
        if score is not None:
            cursor.execute(
                "UPDATE analyses SET score = ? WHERE id = ?",
                (score, row["id"]),
            )
            backfilled += 1

    conn.commit()
    conn.close()
    logger.info("Backfilled %d row(s).", backfilled)
    return backfilled


if __name__ == "__main__":
    sys.exit(0 if migrate() else 1)
