"""create signed collector report tables

Revision ID: 20260910_collector_reports
Revises: 20260831_monthly_profit_goals
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260910_collector_reports"
down_revision: Union[str, Sequence[str], None] = "20260831_monthly_profit_goals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collector_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="received"),
        sa.Column("validation_error", sa.String(length=256), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", name="uq_collector_reports_report_id"),
    )
    op.create_index("ix_collector_reports_symbol", "collector_reports", ["symbol"], unique=False)
    op.create_index("ix_collector_reports_received_at", "collector_reports", ["received_at"], unique=False)
    op.create_table(
        "collector_ingest_replays",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nonce"),
    )
    op.create_table(
        "collector_ingest_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("report_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("validation_error", sa.String(length=64), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collector_ingest_events_nonce", "collector_ingest_events", ["nonce"], unique=False)
    op.create_table(
        "collector_ingest_failures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("validation_error", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nonce"),
    )


def downgrade() -> None:
    op.drop_table("collector_ingest_failures")
    op.drop_index("ix_collector_ingest_events_nonce", table_name="collector_ingest_events")
    op.drop_table("collector_ingest_events")
    op.drop_table("collector_ingest_replays")
    op.drop_index("ix_collector_reports_received_at", table_name="collector_reports")
    op.drop_index("ix_collector_reports_symbol", table_name="collector_reports")
    op.drop_table("collector_reports")
