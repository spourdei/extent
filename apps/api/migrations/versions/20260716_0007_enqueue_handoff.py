"""Make the Redis handoff explicit in durable ingestion state."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0007"
down_revision: str | None = "20260716_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_ingestion_runs_known_status"), "ingestion_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ingestion_runs_known_status"),
        "ingestion_runs",
        "status IN ('enqueue_pending', 'queued', 'discovering', 'processing', "
        "'ready', 'partial', 'fatal', 'retryable')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ingestion_runs SET status = 'retryable' WHERE status = 'enqueue_pending'"
    )
    op.drop_constraint(op.f("ck_ingestion_runs_known_status"), "ingestion_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ingestion_runs_known_status"),
        "ingestion_runs",
        "status IN ('queued', 'discovering', 'processing', 'ready', 'partial', "
        "'fatal', 'retryable')",
    )
