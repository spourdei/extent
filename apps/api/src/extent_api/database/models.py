"""Minimal durable identity schema required by Google OAuth and sessions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from extent_api.database.base import Base


class User(Base):
    """A person identified by a provider account, not by browser state."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(back_populates="user")
    sessions: Mapped[list[Session]] = relationship(back_populates="user")
    workspaces: Mapped[list[Workspace]] = relationship(back_populates="user")


class OAuthAttempt(Base):
    """Single-use, expiring server-side state for an authorization request."""

    __tablename__ = "oauth_attempts"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="consumption_after_creation",
        ),
        Index(
            "ix_oauth_attempts_expires_at_unconsumed",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    state_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    pkce_verifier_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthAccount(Base):
    """One Google identity and its encrypted server-only refresh credential."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        CheckConstraint("token_status IN ('active', 'revoked')", name="known_token_status"),
        CheckConstraint(
            "(token_status = 'active' AND revoked_at IS NULL) OR "
            "(token_status = 'revoked' AND revoked_at IS NOT NULL)",
            name="revocation_matches_status",
        ),
        Index(
            "uq_oauth_accounts_provider_subject",
            "provider",
            "provider_subject",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="google")
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    refresh_token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_key_version: Mapped[int] = mapped_column(nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    token_status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="oauth_accounts")


class Session(Base):
    """Hashed opaque browser session; the plaintext token is never persisted."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revocation_after_creation",
        ),
        Index(
            "ix_sessions_user_id_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class Workspace(Base):
    """One user-owned Drive root created through an idempotent browser action."""

    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="owner_idempotency_key"),
        Index("ix_workspaces_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    root_folder_id: Mapped[str] = mapped_column(String(200), nullable=False)
    root_resource_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="workspaces")
    ingestion_runs: Mapped[list[IngestionRun]] = relationship(back_populates="workspace")
    messages: Mapped[list[Message]] = relationship(back_populates="workspace")
    answers: Mapped[list[Answer]] = relationship(back_populates="workspace")


class IngestionRun(Base):
    """Durable product state for the single bounded folder-discovery job."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('enqueue_pending', 'queued', 'discovering', 'processing', "
            "'ready', 'partial', 'failed', 'retryable')",
            name="known_status",
        ),
        CheckConstraint(
            "attempt_count IS NULL OR attempt_count BETWEEN 0 AND 3",
            name="bounded_attempt_count",
        ),
        CheckConstraint(
            "pipeline_version IS NULL OR pipeline_version = 'drive-ingestion-v1'",
            name="known_pipeline_version",
        ),
        Index("ix_ingestion_runs_workspace_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int | None] = mapped_column(Integer)
    pipeline_version: Mapped[str | None] = mapped_column(String(32))
    root_name: Mapped[str | None] = mapped_column(String(1_024))
    discovery_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovered_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capped_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    folders_visited: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gap_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship(back_populates="ingestion_runs")
    source_files: Mapped[list[SourceFile]] = relationship(back_populates="run")


class SourceFile(Base):
    """Every discovered file remains visible, including unsupported and capped files."""

    __tablename__ = "source_files"
    __table_args__ = (
        CheckConstraint(
            "status IN ('discovered', 'admitted', 'downloading', 'parsed', "
            "'embedding', 'ready', 'retryable_failed', 'terminal_failed', "
            "'unsupported', 'capped')",
            name="known_status",
        ),
        CheckConstraint(
            "error_stage IS NULL OR error_stage IN "
            "('admission', 'download', 'parse', 'embedding')",
            name="known_error_stage",
        ),
        CheckConstraint(
            "pipeline_version IS NULL OR pipeline_version IN "
            "('csv-record-v1', 'csv-record-v2', 'docx-body-v1', 'docx-body-v2', "
            "'pdf-ocr-page-v1', "
            "'pdf-page-v1', 'plain-text-line-v1', 'xlsx-sheet-v1')",
            name="known_pipeline_version",
        ),
        UniqueConstraint("run_id", "drive_file_id", name="run_drive_file"),
        Index("ix_source_files_run_id_ordinal", "run_id", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    drive_file_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(1_024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    ingestion_mode: Mapped[str | None] = mapped_column(String(32))
    resource_key: Mapped[str | None] = mapped_column(String(200))
    modified_time: Mapped[str | None] = mapped_column(String(80))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    pipeline_version: Mapped[str | None] = mapped_column(String(32))
    page_count: Mapped[int | None] = mapped_column(Integer)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_stage: Mapped[str | None] = mapped_column(String(16))
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped[IngestionRun] = relationship(back_populates="source_files")
    blocks: Mapped[list[SourceBlock]] = relationship(back_populates="source_file")


class SourceBlock(Base):
    """A page-addressable normalized evidence block from one immutable source download."""

    __tablename__ = "source_blocks"
    __table_args__ = (
        CheckConstraint(
            "normalized_end_exclusive > normalized_start", name="non_empty_normalized_span"
        ),
        CheckConstraint("origin_kind IN ('pdf_page', 'text_lines')", name="known_origin_kind"),
        CheckConstraint(
            "(origin_kind = 'pdf_page' AND page_index_zero_based IS NOT NULL "
            "AND line_start_one_based IS NULL) OR "
            "(origin_kind = 'text_lines' AND page_index_zero_based IS NULL "
            "AND line_start_one_based IS NOT NULL)",
            name="origin_fields_match_kind",
        ),
        CheckConstraint(
            "pipeline_version IS NULL OR pipeline_version IN "
            "('csv-record-v1', 'csv-record-v2', 'docx-body-v1', 'docx-body-v2', "
            "'pdf-ocr-page-v1', "
            "'pdf-page-v1', 'plain-text-line-v1', 'xlsx-sheet-v1')",
            name="known_pipeline_version",
        ),
        UniqueConstraint(
            "source_file_id",
            "source_content_hash",
            "pipeline_version",
            "ordinal",
            name="source_artifact_ordinal",
        ),
        Index("ix_source_blocks_workspace_run", "workspace_id", "run_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_file_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("source_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    page_index_zero_based: Mapped[int | None] = mapped_column(Integer)
    line_start_one_based: Mapped[int | None] = mapped_column(Integer)
    printed_page_label: Mapped[str | None] = mapped_column(String(40))
    normalized_start: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_end_exclusive: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    embedding_configuration_id: Mapped[str | None] = mapped_column(String(64))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    embedding_model: Mapped[str | None] = mapped_column(String(160))
    source_content_hash: Mapped[str | None] = mapped_column(String(64))
    normalized_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str | None] = mapped_column(String(32))
    structured_metadata: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source_file: Mapped[SourceFile] = relationship(back_populates="blocks")


class Message(Base):
    """Ordered conversation/progress row created with the workspace transaction."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('system', 'user', 'assistant')", name="known_role"),
        CheckConstraint("kind IN ('progress', 'question', 'answer')", name="known_kind"),
        UniqueConstraint("workspace_id", "ordinal", name="workspace_ordinal"),
        UniqueConstraint("workspace_id", "idempotency_key", name="workspace_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="messages")


class Answer(Base):
    """Durable result of one question against one immutable ingestion run."""

    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('evidence_retrieved', 'evidence_supported', 'changed', "
            "'conflict', 'insufficient', 'coverage_limited')",
            name="known_status",
        ),
        CheckConstraint(
            "generation_status IN ('not_configured', 'failed', 'completed')",
            name="known_generation_status",
        ),
        UniqueConstraint("question_message_id", name="question_message"),
        UniqueConstraint("response_message_id", name="response_message"),
        Index("ix_answers_workspace_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    question_message_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    response_message_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    generation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    coverage_gap_reasons: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="answers")
    claims: Mapped[list[AnswerClaim]] = relationship(back_populates="answer")
    citations: Mapped[list[AnswerCitation]] = relationship(back_populates="answer")


class AnswerClaim(Base):
    """A claim that survived deterministic publication authorization."""

    __tablename__ = "answer_claims"
    __table_args__ = (
        CheckConstraint(
            "relation IN ('fact', 'change', 'conflict', 'unclear')",
            name="known_relation",
        ),
        UniqueConstraint("answer_id", "ordinal", name="answer_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    answer_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(String(120))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    answer: Mapped[Answer] = relationship(back_populates="claims")
    citations: Mapped[list[AnswerCitation]] = relationship(back_populates="claim")


class AnswerCitation(Base):
    """Exact source span retained for retrieval or an approved claim."""

    __tablename__ = "answer_citations"
    __table_args__ = (
        CheckConstraint("kind IN ('retrieved', 'claim')", name="known_kind"),
        CheckConstraint(
            "(kind = 'retrieved' AND claim_id IS NULL) OR "
            "(kind = 'claim' AND claim_id IS NOT NULL)",
            name="kind_matches_claim",
        ),
        CheckConstraint("end_exclusive_in_block > start_in_block", name="non_empty_span"),
        CheckConstraint(
            "role IS NULL OR role IN ('support', 'before', 'after', 'left', 'right')",
            name="known_role",
        ),
        CheckConstraint(
            "(raw_value IS NULL AND normalized_value IS NULL) OR "
            "(raw_value IS NOT NULL AND normalized_value IS NOT NULL)",
            name="value_pair",
        ),
        UniqueConstraint("answer_id", "ordinal", name="answer_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    answer_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("answer_claims.id", ondelete="CASCADE")
    )
    source_block_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("source_blocks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(String(120))
    exact_quote: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str | None] = mapped_column(String(16))
    start_in_block: Mapped[int] = mapped_column(Integer, nullable=False)
    end_exclusive_in_block: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    answer: Mapped[Answer] = relationship(back_populates="citations")
    claim: Mapped[AnswerClaim | None] = relationship(back_populates="citations")
