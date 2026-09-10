"""Real Alembic upgrade/downgrade coverage for the webhook outbox."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_signal_webhook_outbox_migration_round_trip(tmp_path, monkeypatch):
    database_path = tmp_path / "webhook-migration.db"
    monkeypatch.setenv("DATABASE_URL", str(database_path))
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "backend" / "alembic.ini"))

    assert ScriptDirectory.from_config(config).get_heads() == [
        "20260910_collector_reports",
    ]

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
        migration_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        collector_failure_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(collector_ingest_failures)")
        }

    assert version == "20260910_collector_reports"
    assert {
        "monthly_profit_goals",
        "collector_reports",
        "collector_ingest_replays",
        "collector_ingest_events",
        "collector_ingest_failures",
    } <= migration_tables
    assert {
        "delivery_id",
        "payload",
        "config_fingerprint",
        "status",
        "attempts",
        "lease_expires_at",
    } <= columns
    assert {row[2] for row in foreign_keys} == {"users", "alert_channels"}
    assert {"nonce", "request_digest", "validation_error", "received_at"} <= collector_failure_columns

    command.downgrade(config, "20260804_phase2b_capital_flow")
    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='signal_webhook_deliveries'"
        ).fetchone()
        migration_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert version == "20260804_phase2b_capital_flow"
    assert table is None
    assert not {
        "monthly_profit_goals",
        "collector_reports",
        "collector_ingest_replays",
        "collector_ingest_events",
        "collector_ingest_failures",
    } & migration_tables
