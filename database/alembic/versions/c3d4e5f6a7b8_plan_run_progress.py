"""add persisted plan run progress

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plan_runs", sa.Column("stage_message", sa.Text(), nullable=True))
    op.add_column("plan_runs", sa.Column("progress", sa.Float(), server_default="0", nullable=True))
    op.add_column("plan_runs", sa.Column("cache_hit", sa.Boolean(), server_default=sa.false(), nullable=True))
    op.add_column("plan_runs", sa.Column("evidence_eligible", sa.Boolean(), server_default=sa.false(), nullable=True))
    op.add_column("plan_runs", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.create_index("ix_plan_runs_evidence", "plan_runs", ["user_id", "status", "evidence_eligible"])


def downgrade() -> None:
    op.drop_index("ix_plan_runs_evidence", table_name="plan_runs")
    op.drop_column("plan_runs", "request_fingerprint")
    op.drop_column("plan_runs", "evidence_eligible")
    op.drop_column("plan_runs", "cache_hit")
    op.drop_column("plan_runs", "progress")
    op.drop_column("plan_runs", "stage_message")
