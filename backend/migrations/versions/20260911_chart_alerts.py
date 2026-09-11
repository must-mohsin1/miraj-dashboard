"""add durable chart alert preferences and event history

Revision ID: 20260911_chart_alerts
Revises: 20260911_chart_drawings
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260911_chart_alerts"
down_revision: Union[str, Sequence[str], None] = "20260911_chart_drawings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chart_alert_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "symbol", "timeframe", name="uq_chart_alert_preference_scope"),
    )
    op.create_index(op.f("ix_chart_alert_preferences_user_id"), "chart_alert_preferences", ["user_id"])

    op.create_table(
        "chart_alert_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("candle_time", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_key", name="uq_chart_alert_event_user_key"),
    )
    op.create_index(op.f("ix_chart_alert_events_user_id"), "chart_alert_events", ["user_id"])
    op.create_index(
        "ix_chart_alert_events_user_scope",
        "chart_alert_events",
        ["user_id", "symbol", "timeframe", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chart_alert_events_user_scope", table_name="chart_alert_events")
    op.drop_index(op.f("ix_chart_alert_events_user_id"), table_name="chart_alert_events")
    op.drop_table("chart_alert_events")
    op.drop_index(op.f("ix_chart_alert_preferences_user_id"), table_name="chart_alert_preferences")
    op.drop_table("chart_alert_preferences")
