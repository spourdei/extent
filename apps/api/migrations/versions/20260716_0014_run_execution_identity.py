"""Persist ingestion run execution identity without inventing legacy history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0014"
down_revision: str | None = "20260716_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_runs", sa.Column("attempt_count", sa.Integer()))
    op.add_column("ingestion_runs", sa.Column("pipeline_version", sa.String(length=32)))
    op.create_check_constraint(
        op.f("ck_ingestion_runs_nonnegative_attempt_count"),
        "ingestion_runs",
        "attempt_count IS NULL OR attempt_count >= 0",
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_known_pipeline_version"),
        "ingestion_runs",
        "pipeline_version IS NULL OR pipeline_version = 'drive-ingestion-v1'",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_ingestion_runs_known_pipeline_version"),
        "ingestion_runs",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_ingestion_runs_nonnegative_attempt_count"),
        "ingestion_runs",
        type_="check",
    )
    op.drop_column("ingestion_runs", "pipeline_version")
    op.drop_column("ingestion_runs", "attempt_count")
