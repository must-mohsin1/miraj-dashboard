"""create realtime advisory signal state

Revision ID: 8a9c1d2e3f4b
Revises: 6fc858c9a128
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8a9c1d2e3f4b"
down_revision: Union[str, Sequence[str], None] = "6fc858c9a128"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "realtime_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("dedup_key", sa.String(length=100), nullable=False),
        sa.Column("transition_count", sa.Integer(), nullable=False),
        sa.Column("missing_gates", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "pair", "direction", name="uq_realtime_signal_user_pair_direction"),
    )
    op.create_index("ix_realtime_signals_user_pair", "realtime_signals", ["user_id", "pair"], unique=False)
    op.create_index("ix_realtime_signals_user_id", "realtime_signals", ["user_id"], unique=False)
    op.create_table(
        "realtime_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["signal_id"], ["realtime_signals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["alert_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", "channel_id", "dedup_key", name="uq_realtime_notification_delivery"),
    )
    op.create_index("ix_realtime_notifications_status", "realtime_notifications", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_realtime_notifications_status", table_name="realtime_notifications")
    op.drop_table("realtime_notifications")
    op.drop_index("ix_realtime_signals_user_id", table_name="realtime_signals")
    op.drop_index("ix_realtime_signals_user_pair", table_name="realtime_signals")
    op.drop_table("realtime_signals")
