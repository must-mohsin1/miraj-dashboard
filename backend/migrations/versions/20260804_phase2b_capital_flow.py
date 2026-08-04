"""phase2b capital flow ledger

Revision ID: 20260804_phase2b_capital_flow
Revises: 20260725_phase2a_mexc_sync
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260804_phase2b_capital_flow"
down_revision: Union[str, Sequence[str], None] = "20260725_phase2a_mexc_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "capital_flow_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("exchange_entry_id", sa.String(length=128), nullable=True),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("signed_amount", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_capital_flow_ledger_user_id"),
        "capital_flow_ledger",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_capital_flow_user_exchange_occurred",
        "capital_flow_ledger",
        ["user_id", "exchange", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "uq_capital_flow_user_exchange_type_source_id",
        "capital_flow_ledger",
        ["user_id", "exchange", "entry_type", "exchange_entry_id"],
        unique=True,
        sqlite_where=sa.text("exchange_entry_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_capital_flow_user_exchange_type_source_id", table_name="capital_flow_ledger")
    op.drop_index("ix_capital_flow_user_exchange_occurred", table_name="capital_flow_ledger")
    op.drop_index(op.f("ix_capital_flow_ledger_user_id"), table_name="capital_flow_ledger")
    op.drop_table("capital_flow_ledger")
