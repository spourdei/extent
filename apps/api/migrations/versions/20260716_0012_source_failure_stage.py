"""Persist the safe processing stage for each source failure."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0012"
down_revision: str | None = "20260716_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_files", sa.Column("error_stage", sa.String(length=16)))
    op.create_check_constraint(
        op.f("ck_source_files_known_error_stage"),
        "source_files",
        "error_stage IS NULL OR error_stage IN ('admission', 'download', 'parse', 'embedding')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_source_files_known_error_stage"), "source_files", type_="check")
    op.drop_column("source_files", "error_stage")
