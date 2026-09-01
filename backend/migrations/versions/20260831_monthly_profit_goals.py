"""monthly profit goals

Revision ID: 20260831_monthly_profit_goals
Revises: 20260809_signal_webhook_outbox
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_monthly_profit_goals"
down_revision: Union[str, Sequence[str], None] = "20260809_signal_webhook_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monthly_profit_goals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("target_return_pct", sa.Float(), nullable=False),
        sa.Column("base_equity", sa.Float(), nullable=True),
        sa.Column("base_source", sa.String(length=32), nullable=True),
        sa.Column("redeem_pct", sa.Float(), nullable=False),
        sa.Column("reinvest_pct", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closing_equity", sa.Float(), nullable=True),
        sa.Column("net_external_flows", sa.Float(), nullable=True),
        sa.Column("net_profit", sa.Float(), nullable=True),
        sa.Column("realized_return_pct", sa.Float(), nullable=True),
        sa.Column("declared_redeem_usd", sa.Float(), nullable=True),
        sa.Column("declared_reinvest_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "exchange", "period_year", "period_month",
            name="uq_monthly_profit_goal_period",
        ),
    )
    op.create_index(
        "ix_monthly_profit_goals_user_exchange",
        "monthly_profit_goals",
        ["user_id", "exchange"],
    )
    op.create_index(op.f("ix_monthly_profit_goals_user_id"), "monthly_profit_goals", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_monthly_profit_goals_user_id"), table_name="monthly_profit_goals")
    op.drop_index("ix_monthly_profit_goals_user_exchange", table_name="monthly_profit_goals")
    op.drop_table("monthly_profit_goals")
