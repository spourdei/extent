"""Add line-addressable origins for admitted plain-text evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0005"
down_revision: str | None = "20260716_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_blocks",
        sa.Column(
            "origin_kind",
            sa.String(length=16),
            nullable=False,
            server_default="pdf_page",
        ),
    )
    op.add_column("source_blocks", sa.Column("line_start_one_based", sa.Integer()))
    op.alter_column("source_blocks", "page_index_zero_based", nullable=True)
    op.alter_column("source_blocks", "origin_kind", server_default=None)
    op.create_check_constraint(
        op.f("ck_source_blocks_known_origin_kind"),
        "source_blocks",
        "origin_kind IN ('pdf_page', 'text_lines')",
    )
    op.create_check_constraint(
        op.f("ck_source_blocks_origin_fields_match_kind"),
        "source_blocks",
        "(origin_kind = 'pdf_page' AND page_index_zero_based IS NOT NULL "
        "AND line_start_one_based IS NULL) OR "
        "(origin_kind = 'text_lines' AND page_index_zero_based IS NULL "
        "AND line_start_one_based IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_source_blocks_origin_fields_match_kind"),
        "source_blocks",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_source_blocks_known_origin_kind"), "source_blocks", type_="check"
    )
    op.alter_column("source_blocks", "page_index_zero_based", nullable=False)
    op.drop_column("source_blocks", "line_start_one_based")
    op.drop_column("source_blocks", "origin_kind")
