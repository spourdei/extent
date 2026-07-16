"""Admit CSV record and DOCX body artifacts as active source pipelines."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0018"
down_revision: str | None = "20260716_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS_PIPELINES = "'pdf-ocr-page-v1', 'pdf-page-v1', 'plain-text-line-v1'"
_WITH_STRUCTURED_DOCUMENTS = "'csv-record-v1', 'docx-body-v1', " + _PREVIOUS_PIPELINES


def upgrade() -> None:
    _replace_pipeline_constraints(_WITH_STRUCTURED_DOCUMENTS)


def downgrade() -> None:
    _replace_pipeline_constraints(_PREVIOUS_PIPELINES)


def _replace_pipeline_constraints(known_pipelines: str) -> None:
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
    op.create_check_constraint(
        op.f("ck_source_files_known_pipeline_version"),
        "source_files",
        f"pipeline_version IS NULL OR pipeline_version IN ({known_pipelines})",
    )
    op.create_check_constraint(
        op.f("ck_source_blocks_known_pipeline_version"),
        "source_blocks",
        f"pipeline_version IS NULL OR pipeline_version IN ({known_pipelines})",
    )
