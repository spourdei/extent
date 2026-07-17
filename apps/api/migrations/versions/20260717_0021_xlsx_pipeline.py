"""Admit bounded XLSX sheet artifacts as an active source pipeline."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0021"
down_revision: str | None = "20260717_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_V2_PIPELINES = (
    "'csv-record-v1', 'csv-record-v2', 'docx-body-v1', 'docx-body-v2', "
    "'pdf-ocr-page-v1', 'pdf-page-v1', 'plain-text-line-v1'"
)
_WITH_XLSX = _V2_PIPELINES + ", 'xlsx-sheet-v1'"


def upgrade() -> None:
    _replace_pipeline_constraints(_WITH_XLSX)


def downgrade() -> None:
    _replace_pipeline_constraints(_V2_PIPELINES)


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
