"""Add page-addressable PDF evidence blocks and per-file parsing state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0003"
down_revision: str | None = "20260716_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_ingestion_runs_known_status"), "ingestion_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ingestion_runs_known_status"),
        "ingestion_runs",
        "status IN ('queued', 'discovering', 'processing', 'ready', 'partial', "
        "'fatal', 'retryable')",
    )
    op.drop_constraint(op.f("ck_source_files_known_status"), "source_files", type_="check")
    op.create_check_constraint(
        op.f("ck_source_files_known_status"),
        "source_files",
        "status IN ('queued', 'parsing', 'ready', 'failed', 'unsupported', 'capped')",
    )
    op.add_column("source_files", sa.Column("resource_key", sa.String(length=200)))
    op.add_column("source_files", sa.Column("content_hash", sa.String(length=64)))
    op.add_column("source_files", sa.Column("page_count", sa.Integer()))
    op.add_column(
        "source_files",
        sa.Column("block_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("source_files", sa.Column("error_code", sa.String(length=80)))
    op.add_column("source_files", sa.Column("parsed_at", sa.DateTime(timezone=True)))
    op.alter_column("source_files", "block_count", server_default=None)

    op.create_table(
        "source_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_index_zero_based", sa.Integer(), nullable=False),
        sa.Column("printed_page_label", sa.String(length=40)),
        sa.Column("normalized_start", sa.Integer(), nullable=False),
        sa.Column("normalized_end_exclusive", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "normalized_end_exclusive > normalized_start",
            name=op.f("ck_source_blocks_non_empty_normalized_span"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_source_blocks_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_source_blocks_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["source_files.id"],
            name=op.f("fk_source_blocks_source_file_id_source_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_blocks")),
        sa.UniqueConstraint(
            "source_file_id", "ordinal", name=op.f("uq_source_blocks_source_ordinal")
        ),
    )
    op.create_index(
        "ix_source_blocks_workspace_run", "source_blocks", ["workspace_id", "run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_blocks_workspace_run", table_name="source_blocks")
    op.drop_table("source_blocks")
    op.drop_column("source_files", "parsed_at")
    op.drop_column("source_files", "error_code")
    op.drop_column("source_files", "block_count")
    op.drop_column("source_files", "page_count")
    op.drop_column("source_files", "content_hash")
    op.drop_column("source_files", "resource_key")
    op.drop_constraint(op.f("ck_source_files_known_status"), "source_files", type_="check")
    op.create_check_constraint(
        op.f("ck_source_files_known_status"),
        "source_files",
        "status IN ('queued', 'unsupported', 'capped')",
    )
    op.drop_constraint(op.f("ck_ingestion_runs_known_status"), "ingestion_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_ingestion_runs_known_status"),
        "ingestion_runs",
        "status IN ('queued', 'discovering', 'ready', 'partial', 'fatal', 'retryable')",
    )
