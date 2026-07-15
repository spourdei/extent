"""Add the owner-scoped Drive workspace discovery slice."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0002"
down_revision: str | None = "20260715_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("root_folder_id", sa.String(length=200), nullable=False),
        sa.Column("root_resource_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workspaces_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name=op.f("uq_workspaces_owner_idempotency_key")
        ),
    )
    op.create_index("ix_workspaces_user_id_created_at", "workspaces", ["user_id", "created_at"])
    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("root_name", sa.String(length=1024), nullable=True),
        sa.Column("discovery_complete", sa.Boolean(), nullable=False),
        sa.Column("discovered_files", sa.Integer(), nullable=False),
        sa.Column("queued_files", sa.Integer(), nullable=False),
        sa.Column("unsupported_files", sa.Integer(), nullable=False),
        sa.Column("capped_files", sa.Integer(), nullable=False),
        sa.Column("folders_visited", sa.Integer(), nullable=False),
        sa.Column("gap_reasons", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'discovering', 'ready', 'partial', 'fatal', 'retryable')",
            name=op.f("ck_ingestion_runs_known_status"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_ingestion_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(
        "ix_ingestion_runs_workspace_created_at",
        "ingestion_runs",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('progress', 'question', 'answer')", name=op.f("ck_messages_known_kind")
        ),
        sa.CheckConstraint(
            "role IN ('system', 'user', 'assistant')", name=op.f("ck_messages_known_role")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_messages_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "workspace_id", "ordinal", name=op.f("uq_messages_workspace_ordinal")
        ),
    )
    op.create_table(
        "source_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("drive_file_id", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("path", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("ingestion_mode", sa.String(length=32), nullable=True),
        sa.Column("modified_time", sa.String(length=80), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'unsupported', 'capped')",
            name=op.f("ck_source_files_known_status"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_source_files_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_files")),
        sa.UniqueConstraint(
            "run_id", "drive_file_id", name=op.f("uq_source_files_run_drive_file")
        ),
    )
    op.create_index("ix_source_files_run_id_ordinal", "source_files", ["run_id", "ordinal"])


def downgrade() -> None:
    op.drop_index("ix_source_files_run_id_ordinal", table_name="source_files")
    op.drop_table("source_files")
    op.drop_table("messages")
    op.drop_index("ix_ingestion_runs_workspace_created_at", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_index("ix_workspaces_user_id_created_at", table_name="workspaces")
    op.drop_table("workspaces")
