"""Persist idempotent questions, answers, approved claims, and exact citations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0004"
down_revision: str | None = "20260716_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("idempotency_key", sa.String(length=128)))
    op.create_unique_constraint(
        op.f("uq_messages_workspace_idempotency_key"),
        "messages",
        ["workspace_id", "idempotency_key"],
    )

    op.create_table(
        "answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("response_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generation_status", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("coverage_gap_reasons", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('evidence_retrieved', 'evidence_supported', 'changed', "
            "'conflict', 'insufficient', 'coverage_limited')",
            name=op.f("ck_answers_known_status"),
        ),
        sa.CheckConstraint(
            "generation_status IN ('not_configured', 'completed')",
            name=op.f("ck_answers_known_generation_status"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_answers_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_answers_ingestion_run_id_ingestion_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["question_message_id"],
            ["messages.id"],
            name=op.f("fk_answers_question_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["response_message_id"],
            ["messages.id"],
            name=op.f("fk_answers_response_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_answers")),
        sa.UniqueConstraint("question_message_id", name=op.f("uq_answers_question_message")),
        sa.UniqueConstraint("response_message_id", name=op.f("uq_answers_response_message")),
    )
    op.create_index(
        "ix_answers_workspace_created_at", "answers", ["workspace_id", "created_at"]
    )

    op.create_table(
        "answer_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("value", sa.String(length=120)),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "relation IN ('fact', 'change', 'conflict', 'unclear')",
            name=op.f("ck_answer_claims_known_relation"),
        ),
        sa.ForeignKeyConstraint(
            ["answer_id"],
            ["answers.id"],
            name=op.f("fk_answer_claims_answer_id_answers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_answer_claims")),
        sa.UniqueConstraint(
            "answer_id", "ordinal", name=op.f("uq_answer_claims_answer_ordinal")
        ),
    )

    op.create_table(
        "answer_citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("exact_quote", sa.Text(), nullable=False),
        sa.Column("start_in_block", sa.Integer(), nullable=False),
        sa.Column("end_exclusive_in_block", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('retrieved', 'claim')", name=op.f("ck_answer_citations_known_kind")
        ),
        sa.CheckConstraint(
            "(kind = 'retrieved' AND claim_id IS NULL) OR "
            "(kind = 'claim' AND claim_id IS NOT NULL)",
            name=op.f("ck_answer_citations_kind_matches_claim"),
        ),
        sa.CheckConstraint(
            "end_exclusive_in_block > start_in_block",
            name=op.f("ck_answer_citations_non_empty_span"),
        ),
        sa.ForeignKeyConstraint(
            ["answer_id"],
            ["answers.id"],
            name=op.f("fk_answer_citations_answer_id_answers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["answer_claims.id"],
            name=op.f("fk_answer_citations_claim_id_answer_claims"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_block_id"],
            ["source_blocks.id"],
            name=op.f("fk_answer_citations_source_block_id_source_blocks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_answer_citations")),
        sa.UniqueConstraint(
            "answer_id", "ordinal", name=op.f("uq_answer_citations_answer_ordinal")
        ),
    )


def downgrade() -> None:
    op.drop_table("answer_citations")
    op.drop_table("answer_claims")
    op.drop_index("ix_answers_workspace_created_at", table_name="answers")
    op.drop_table("answers")
    op.drop_constraint(
        op.f("uq_messages_workspace_idempotency_key"), "messages", type_="unique"
    )
    op.drop_column("messages", "idempotency_key")
