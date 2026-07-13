"""collection reliability fields

RawDocument: source_url/published_at/last_error/retry_count/processed_at
Event: summary_embedding/enriched_query_embedding/embedding_model/text_source/text_quality/category

Revision ID: a1b2c3d4e5f6
Revises: 01ddd876e3f0
Create Date: 2026-07-13 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '01ddd876e3f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # RawDocument 采集可靠性扩展
    op.add_column('raw_documents', sa.Column('source_url', sa.String(length=500), nullable=True))
    op.add_column('raw_documents', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('raw_documents', sa.Column('last_error', sa.Text(), nullable=True))
    op.add_column('raw_documents', sa.Column('retry_count', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('raw_documents', sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True))

    # Event 采集可靠性扩展
    op.add_column('events', sa.Column('summary_embedding', sa.JSON(), nullable=True))
    op.add_column('events', sa.Column('enriched_query_embedding', sa.JSON(), nullable=True))
    op.add_column('events', sa.Column('embedding_model', sa.String(length=50), nullable=True))
    op.add_column('events', sa.Column('text_source', sa.String(length=20), nullable=True))
    op.add_column('events', sa.Column('text_quality', sa.String(length=20), nullable=True))
    op.add_column('events', sa.Column('category', sa.String(length=20), nullable=True))

    # 规范化已有 raw_documents.url → source_url（一次性回填）
    op.execute("UPDATE raw_documents SET source_url = url WHERE source_url IS NULL AND url IS NOT NULL")


def downgrade() -> None:
    op.drop_column('events', 'category')
    op.drop_column('events', 'text_quality')
    op.drop_column('events', 'text_source')
    op.drop_column('events', 'embedding_model')
    op.drop_column('events', 'enriched_query_embedding')
    op.drop_column('events', 'summary_embedding')

    op.drop_column('raw_documents', 'processed_at')
    op.drop_column('raw_documents', 'retry_count')
    op.drop_column('raw_documents', 'last_error')
    op.drop_column('raw_documents', 'published_at')
    op.drop_column('raw_documents', 'source_url')
