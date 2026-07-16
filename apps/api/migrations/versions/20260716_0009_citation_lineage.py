"""Persist approved evidence roles and canonical comparison values."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0009"
down_revision: str | None = "20260716_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answer_citations", sa.Column("role", sa.String(length=16)))
    op.add_column("answer_citations", sa.Column("raw_value", sa.String(length=120)))
    op.add_column("answer_citations", sa.Column("normalized_value", sa.String(length=120)))
    op.create_check_constraint(
        op.f("ck_answer_citations_known_role"),
        "answer_citations",
        "role IS NULL OR role IN ('support', 'before', 'after', 'left', 'right')",
    )
    op.create_check_constraint(
        op.f("ck_answer_citations_value_pair"),
        "answer_citations",
        "(raw_value IS NULL AND normalized_value IS NULL) OR "
        "(raw_value IS NOT NULL AND normalized_value IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_answer_citations_value_pair"), "answer_citations", type_="check"
    )
    op.drop_constraint(
        op.f("ck_answer_citations_known_role"), "answer_citations", type_="check"
    )
    op.drop_column("answer_citations", "normalized_value")
    op.drop_column("answer_citations", "raw_value")
    op.drop_column("answer_citations", "role")
