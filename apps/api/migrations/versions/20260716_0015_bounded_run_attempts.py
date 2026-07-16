"""Bound known ingestion execution attempts to the initial run plus two retries."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0015"
down_revision: str | None = "20260716_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_ingestion_runs_nonnegative_attempt_count"),
        "ingestion_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_bounded_attempt_count"),
        "ingestion_runs",
        "attempt_count IS NULL OR attempt_count BETWEEN 0 AND 3",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_ingestion_runs_bounded_attempt_count"),
        "ingestion_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_nonnegative_attempt_count"),
        "ingestion_runs",
        "attempt_count IS NULL OR attempt_count >= 0",
    )
