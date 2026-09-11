"""add durable user chart drawings

Revision ID: 20260911_chart_drawings
Revises: 20260910_collector_reports
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260911_chart_drawings"
down_revision: Union[str, Sequence[str], None] = "20260910_collector_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chart_drawings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("drawing_id", sa.String(length=64), nullable=False),
        sa.Column("drawing_type", sa.String(length=16), nullable=False),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("style", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "symbol", "timeframe", "drawing_id",
            name="uq_chart_drawing_scope_id",
        ),
    )
    op.create_index(
        "ix_chart_drawings_user_scope",
        "chart_drawings",
        ["user_id", "symbol", "timeframe"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chart_drawings_user_id"),
        "chart_drawings",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chart_drawings_user_id"), table_name="chart_drawings")
    op.drop_index("ix_chart_drawings_user_scope", table_name="chart_drawings")
    op.drop_table("chart_drawings")
