"""Narrow active source pipelines to the released parser scope."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0016"
down_revision: str | None = "20260716_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_PIPELINES = "'pdf-page-v1', 'plain-text-line-v1'"
_HISTORICAL_PIPELINES = "'csv-record-v1', 'docx-body-v1'"
_ALL_PIPELINES = f"{_HISTORICAL_PIPELINES}, {_ACTIVE_PIPELINES}"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            WITH affected_runs AS (
                SELECT DISTINCT run_id
                FROM source_files
                WHERE pipeline_version IN ({_HISTORICAL_PIPELINES})
            ), remaining_ready AS (
                SELECT
                    affected_runs.run_id,
                    count(source_files.id) FILTER (
                        WHERE source_files.status = 'ready'
                        AND source_files.pipeline_version NOT IN ({_HISTORICAL_PIPELINES})
                    ) AS ready_count,
                    count(source_files.id) FILTER (
                        WHERE source_files.status = 'unsupported'
                        OR source_files.pipeline_version IN ({_HISTORICAL_PIPELINES})
                    ) AS unsupported_count
                FROM affected_runs
                LEFT JOIN source_files ON source_files.run_id = affected_runs.run_id
                GROUP BY affected_runs.run_id
            )
            UPDATE ingestion_runs
            SET
                status = CASE
                    WHEN ingestion_runs.status IN ('ready', 'partial', 'failed')
                    THEN CASE
                        WHEN remaining_ready.ready_count > 0 THEN 'partial'
                        ELSE 'failed'
                    END
                    ELSE ingestion_runs.status
                END,
                unsupported_files = remaining_ready.unsupported_count::integer,
                gap_reasons = CASE
                    WHEN 'unsupported' = ANY(ingestion_runs.gap_reasons)
                    THEN ingestion_runs.gap_reasons
                    ELSE array_append(ingestion_runs.gap_reasons, 'unsupported')
                END,
                error_code = CASE
                    WHEN ingestion_runs.status IN ('ready', 'partial', 'failed')
                    THEN CASE
                        WHEN remaining_ready.ready_count > 0 THEN NULL
                        ELSE 'no_ready_sources'
                    END
                    ELSE ingestion_runs.error_code
                END
            FROM remaining_ready
            WHERE ingestion_runs.id = remaining_ready.run_id
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE source_files
            SET
                status = 'unsupported',
                block_count = 0,
                page_count = NULL,
                pipeline_version = NULL,
                error_code = 'unsupported_mime_type',
                error_stage = 'admission'
            WHERE pipeline_version IN ({_HISTORICAL_PIPELINES})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE source_blocks
            SET pipeline_version = NULL
            WHERE pipeline_version IN ({_HISTORICAL_PIPELINES})
            """
        )
    )
    _replace_pipeline_constraints(_ACTIVE_PIPELINES)


def downgrade() -> None:
    _replace_pipeline_constraints(_ALL_PIPELINES)


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
