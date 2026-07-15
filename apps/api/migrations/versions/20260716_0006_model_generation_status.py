"""Represent model-provider failure separately from missing configuration."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0006"
down_revision: str | None = "20260716_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_answers_known_generation_status"), "answers", type_="check")
    op.create_check_constraint(
        op.f("ck_answers_known_generation_status"),
        "answers",
        "generation_status IN ('not_configured', 'failed', 'completed')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE answers SET generation_status = 'not_configured' "
        "WHERE generation_status = 'failed'"
    )
    op.drop_constraint(op.f("ck_answers_known_generation_status"), "answers", type_="check")
    op.create_check_constraint(
        op.f("ck_answers_known_generation_status"),
        "answers",
        "generation_status IN ('not_configured', 'completed')",
    )
