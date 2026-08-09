"""create signed signal webhook outbox

Revision ID: 20260809_signal_webhook_outbox
Revises: 20260804_phase2b_capital_flow
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_signal_webhook_outbox"
down_revision: Union[str, Sequence[str], None] = "20260804_phase2b_capital_flow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_webhook_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["alert_channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id",
            "delivery_id",
            "config_fingerprint",
            name="uq_signal_webhook_channel_delivery",
        ),
    )
    op.create_index(
        "ix_signal_webhook_deliveries_channel_id",
        "signal_webhook_deliveries",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_signal_webhook_deliveries_pair",
        "signal_webhook_deliveries",
        ["pair"],
        unique=False,
    )
    op.create_index(
        "ix_signal_webhook_deliveries_status_due",
        "signal_webhook_deliveries",
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_signal_webhook_deliveries_user_id",
        "signal_webhook_deliveries",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_signal_webhook_deliveries_user_id",
        table_name="signal_webhook_deliveries",
    )
    op.drop_index(
        "ix_signal_webhook_deliveries_status_due",
        table_name="signal_webhook_deliveries",
    )
    op.drop_index(
        "ix_signal_webhook_deliveries_pair",
        table_name="signal_webhook_deliveries",
    )
    op.drop_index(
        "ix_signal_webhook_deliveries_channel_id",
        table_name="signal_webhook_deliveries",
    )
    op.drop_table("signal_webhook_deliveries")
