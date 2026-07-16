"""Persist fixed-size source-block embeddings for pgvector retrieval."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260716_0008"
down_revision: str | None = "20260716_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_blocks", sa.Column("embedding", Vector(1536), nullable=True))
    op.create_index(
        "ix_source_blocks_embedding_hnsw",
        "source_blocks",
        ["embedding"],
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_using="hnsw",
    )


def downgrade() -> None:
    op.drop_index("ix_source_blocks_embedding_hnsw", table_name="source_blocks")
    op.drop_column("source_blocks", "embedding")
