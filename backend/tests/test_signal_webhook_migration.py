"""Real Alembic upgrade/downgrade coverage for the webhook outbox."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config


def test_signal_webhook_outbox_migration_round_trip(tmp_path, monkeypatch):
    database_path = tmp_path / "webhook-migration.db"
    monkeypatch.setenv("DATABASE_URL", str(database_path))
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "backend" / "alembic.ini"))

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(signal_webhook_deliveries)"
            )
        }
        foreign_keys = list(
            connection.execute("PRAGMA foreign_key_list(signal_webhook_deliveries)")
        )
        goal_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='monthly_profit_goals'"
        ).fetchone()

    assert version == "20260831_monthly_profit_goals"
    assert goal_table is not None
    assert {
        "delivery_id",
        "payload",
        "config_fingerprint",
        "status",
        "attempts",
        "lease_expires_at",
    } <= columns
    assert {row[2] for row in foreign_keys} == {"users", "alert_channels"}

    command.downgrade(config, "20260804_phase2b_capital_flow")
    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='signal_webhook_deliveries'"
        ).fetchone()

    assert version == "20260804_phase2b_capital_flow"
    assert table is None
