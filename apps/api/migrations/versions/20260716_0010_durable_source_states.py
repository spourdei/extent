"""Persist each durable source-processing stage and failure class."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0010"
down_revision: str | None = "20260716_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_source_files_known_status"), "source_files", type_="check")
    op.execute("UPDATE source_files SET status = 'admitted' WHERE status = 'queued'")
    op.execute("UPDATE source_files SET status = 'retryable_failed' WHERE status = 'parsing'")
    op.execute("UPDATE source_files SET status = 'terminal_failed' WHERE status = 'failed'")
    op.execute(
        "UPDATE ingestion_runs SET status = 'retryable', "
        "error_code = 'source_state_migration_recovery', "
        "finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP) "
        "WHERE status IN ('processing', 'ready', 'partial') AND EXISTS ("
        "SELECT 1 FROM source_files "
        "WHERE source_files.run_id = ingestion_runs.id "
        "AND source_files.status = 'retryable_failed')"
    )
    op.create_check_constraint(
        op.f("ck_source_files_known_status"),
        "source_files",
        "status IN ('discovered', 'admitted', 'downloading', 'parsed', "
        "'embedding', 'ready', 'retryable_failed', 'terminal_failed', "
        "'unsupported', 'capped')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_source_files_known_status"), "source_files", type_="check")
    op.execute(
        "UPDATE ingestion_runs SET status = 'processing', error_code = NULL, "
        "finished_at = NULL WHERE status = 'retryable' "
        "AND error_code = 'source_state_migration_recovery'"
    )
    op.execute(
        "UPDATE source_files SET status = 'queued' WHERE status IN ('discovered', 'admitted')"
    )
    op.execute(
        "UPDATE source_files SET status = 'parsing' "
        "WHERE status IN ('downloading', 'parsed', 'embedding', "
        "'retryable_failed')"
    )
    op.execute("UPDATE source_files SET status = 'failed' WHERE status = 'terminal_failed'")
    op.create_check_constraint(
        op.f("ck_source_files_known_status"),
        "source_files",
        "status IN ('queued', 'parsing', 'ready', 'failed', 'unsupported', 'capped')",
    )
