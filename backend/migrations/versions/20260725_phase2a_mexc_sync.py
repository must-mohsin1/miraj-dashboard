"""phase2a mexc sync schema

Revision ID: 20260725_phase2a_mexc_sync
Revises: a1b2c3d4e5f6
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260725_phase2a_mexc_sync"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("position_history", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_position_history_user_exchange_symbol_close", type_="unique")
        batch_op.add_column(sa.Column("exchange_position_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("reported_pnl", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("reported_roi_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("source_state", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("source_updated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("synced_at", sa.DateTime(), nullable=True))

    op.execute("UPDATE position_history SET reported_pnl = pnl, reported_roi_pct = pnl_percent")
    op.create_index(
        "uq_position_history_user_exchange_source_id",
        "position_history",
        ["user_id", "exchange", "exchange_position_id"],
        unique=True,
        sqlite_where=sa.text("exchange_position_id IS NOT NULL"),
    )

    with op.batch_alter_table("order_history", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_order_history_user_exchange_symbol_ts_side_price", type_="unique")
        batch_op.add_column(sa.Column("exchange_order_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("source_updated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("synced_at", sa.DateTime(), nullable=True))

    op.create_index(
        "uq_order_history_user_exchange_source_id",
        "order_history",
        ["user_id", "exchange", "exchange_order_id"],
        unique=True,
        sqlite_where=sa.text("exchange_order_id IS NOT NULL"),
    )

    op.create_table(
        "futures_account_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("settlement_asset", sa.String(length=32), nullable=False),
        sa.Column("equity", sa.Float(), nullable=True),
        sa.Column("available_balance", sa.Float(), nullable=True),
        sa.Column("frozen_balance", sa.Float(), nullable=True),
        sa.Column("cash_balance", sa.Float(), nullable=True),
        sa.Column("position_margin", sa.Float(), nullable=True),
        sa.Column("unrealized_pnl", sa.Float(), nullable=True),
        sa.Column("bonus", sa.Float(), nullable=True),
        sa.Column("available_cash", sa.Float(), nullable=True),
        sa.Column("debt_amount", sa.Float(), nullable=True),
        sa.Column("source_ts", sa.DateTime(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_futures_account_snapshots_user_exchange",
        "futures_account_snapshots",
        ["user_id", "exchange", "settlement_asset", "source_ts"],
        unique=False,
    )
    op.create_index(
        op.f("ix_futures_account_snapshots_user_id"),
        "futures_account_snapshots",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "exchange_sync_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("stream", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cursor_json", sa.JSON(), nullable=True),
        sa.Column("oldest_source_ts", sa.DateTime(), nullable=True),
        sa.Column("newest_source_ts", sa.DateTime(), nullable=True),
        sa.Column("rows_fetched_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_total", sa.Integer(), nullable=True),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("partial_reason", sa.String(length=128), nullable=True),
        sa.Column("unrecoverable_gaps_json", sa.JSON(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message_redacted", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "exchange", "stream", name="uq_exchange_sync_state_user_exchange_stream"),
    )
    op.create_index(
        "ix_exchange_sync_state_user_exchange",
        "exchange_sync_state",
        ["user_id", "exchange"],
        unique=False,
    )
    op.create_index(
        op.f("ix_exchange_sync_state_user_id"),
        "exchange_sync_state",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_exchange_sync_state_user_id"), table_name="exchange_sync_state")
    op.drop_index("ix_exchange_sync_state_user_exchange", table_name="exchange_sync_state")
    op.drop_table("exchange_sync_state")

    op.drop_index(op.f("ix_futures_account_snapshots_user_id"), table_name="futures_account_snapshots")
    op.drop_index("ix_futures_account_snapshots_user_exchange", table_name="futures_account_snapshots")
    op.drop_table("futures_account_snapshots")

    op.drop_index("uq_order_history_user_exchange_source_id", table_name="order_history")
    with op.batch_alter_table("order_history", recreate="always") as batch_op:
        batch_op.drop_column("synced_at")
        batch_op.drop_column("source_updated_at")
        batch_op.drop_column("exchange_order_id")
        batch_op.create_unique_constraint(
            "uq_order_history_user_exchange_symbol_ts_side_price",
            ["user_id", "exchange", "symbol", "timestamp", "side", "price"],
        )

    op.drop_index("uq_position_history_user_exchange_source_id", table_name="position_history")
    with op.batch_alter_table("position_history", recreate="always") as batch_op:
        batch_op.drop_column("synced_at")
        batch_op.drop_column("source_updated_at")
        batch_op.drop_column("source_state")
        batch_op.drop_column("reported_roi_pct")
        batch_op.drop_column("reported_pnl")
        batch_op.drop_column("exchange_position_id")
        batch_op.create_unique_constraint(
            "uq_position_history_user_exchange_symbol_close",
            ["user_id", "exchange", "symbol", "close_time"],
        )
