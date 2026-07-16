"""Derive terminal ingestion failure from the persisted source manifest."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0011"
down_revision: str | None = "20260716_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_ingestion_runs_known_status"), "ingestion_runs", type_="check")
    op.execute("UPDATE ingestion_runs SET status = 'failed' WHERE status = 'fatal'")
    op.execute(
        "UPDATE ingestion_runs SET status = 'failed', "
        "error_code = COALESCE(error_code, 'no_ready_sources') "
        "WHERE status = 'partial' AND NOT EXISTS ("
        "SELECT 1 FROM source_files "
        "WHERE source_files.run_id = ingestion_runs.id "
        "AND source_files.status = 'ready')"
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_known_status"),
        "ingestion_runs",
        "status IN ('enqueue_pending', 'queued', 'discovering', 'processing', "
        "'ready', 'partial', 'failed', 'retryable')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_ingestion_runs_known_status"), "ingestion_runs", type_="check")
    op.execute(
        "UPDATE ingestion_runs SET status = 'partial', error_code = NULL "
        "WHERE status = 'failed' AND error_code = 'no_ready_sources'"
    )
    op.execute("UPDATE ingestion_runs SET status = 'fatal' WHERE status = 'failed'")
    op.create_check_constraint(
        op.f("ck_ingestion_runs_known_status"),
        "ingestion_runs",
        "status IN ('enqueue_pending', 'queued', 'discovering', 'processing', "
        "'ready', 'partial', 'fatal', 'retryable')",
    )
