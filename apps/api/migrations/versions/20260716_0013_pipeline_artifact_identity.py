"""Persist explicit source pipeline artifact identity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0013"
down_revision: str | None = "20260716_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWN_PIPELINES = "'csv-record-v1', 'docx-body-v1', 'pdf-page-v1', 'plain-text-line-v1'"


def upgrade() -> None:
    op.add_column("source_files", sa.Column("pipeline_version", sa.String(length=32)))
    op.add_column("source_blocks", sa.Column("source_content_hash", sa.String(length=64)))
    op.add_column("source_blocks", sa.Column("pipeline_version", sa.String(length=32)))
    op.alter_column("source_blocks", "content_hash", new_column_name="normalized_content_hash")
    op.drop_constraint(op.f("uq_source_blocks_source_ordinal"), "source_blocks", type_="unique")
    op.create_check_constraint(
        op.f("ck_source_files_known_pipeline_version"),
        "source_files",
        f"pipeline_version IS NULL OR pipeline_version IN ({_KNOWN_PIPELINES})",
    )
    op.create_check_constraint(
        op.f("ck_source_blocks_known_pipeline_version"),
        "source_blocks",
        f"pipeline_version IS NULL OR pipeline_version IN ({_KNOWN_PIPELINES})",
    )
    op.create_unique_constraint(
        op.f("uq_source_blocks_source_artifact_ordinal"),
        "source_blocks",
        ["source_file_id", "source_content_hash", "pipeline_version", "ordinal"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_source_blocks_source_artifact_ordinal"),
        "source_blocks",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_source_blocks_known_pipeline_version"),
        "source_blocks",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_source_files_known_pipeline_version"),
        "source_files",
        type_="check",
    )
    op.create_unique_constraint(
        op.f("uq_source_blocks_source_ordinal"),
        "source_blocks",
        ["source_file_id", "ordinal"],
    )
    op.alter_column("source_blocks", "normalized_content_hash", new_column_name="content_hash")
    op.drop_column("source_blocks", "pipeline_version")
    op.drop_column("source_blocks", "source_content_hash")
    op.drop_column("source_files", "pipeline_version")
