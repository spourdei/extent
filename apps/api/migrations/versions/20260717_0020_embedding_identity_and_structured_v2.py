"""Version structured artifacts and bind vectors to one embedding space."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0020"
down_revision: str | None = "20260717_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_V1_PIPELINES = (
    "'csv-record-v1', 'docx-body-v1', 'pdf-ocr-page-v1', 'pdf-page-v1', 'plain-text-line-v1'"
)
_V2_PIPELINES = (
    "'csv-record-v1', 'csv-record-v2', 'docx-body-v1', 'docx-body-v2', "
    "'pdf-ocr-page-v1', 'pdf-page-v1', 'plain-text-line-v1'"
)


def upgrade() -> None:
    op.add_column("source_blocks", sa.Column("embedding_configuration_id", sa.String(64)))
    op.add_column("source_blocks", sa.Column("embedding_dimensions", sa.Integer()))
    op.add_column("source_blocks", sa.Column("embedding_model", sa.String(160)))
    op.create_index(
        "ix_source_blocks_embedding_configuration",
        "source_blocks",
        ["embedding_configuration_id"],
    )
    _replace_pipeline_constraints(_V2_PIPELINES)


def downgrade() -> None:
    _replace_pipeline_constraints(_V1_PIPELINES)
    op.drop_index("ix_source_blocks_embedding_configuration", table_name="source_blocks")
    op.drop_column("source_blocks", "embedding_model")
    op.drop_column("source_blocks", "embedding_dimensions")
    op.drop_column("source_blocks", "embedding_configuration_id")


def _replace_pipeline_constraints(known_pipelines: str) -> None:
    for table_name in ("source_blocks", "source_files"):
        op.drop_constraint(
            op.f(f"ck_{table_name}_known_pipeline_version"),
            table_name,
            type_="check",
        )
        op.create_check_constraint(
            op.f(f"ck_{table_name}_known_pipeline_version"),
            table_name,
            f"pipeline_version IS NULL OR pipeline_version IN ({known_pipelines})",
        )
