"""add collection run records

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collection_runs",
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_method", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("fetched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extracted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    op.create_index("ix_collection_runs_triggered_at", "collection_runs", ["triggered_at"])


def downgrade() -> None:
    op.drop_index("ix_collection_runs_triggered_at", table_name="collection_runs")
    op.drop_table("collection_runs")
