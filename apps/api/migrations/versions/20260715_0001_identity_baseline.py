"""Create the durable identity and session substrate."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260715_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "oauth_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("pkce_verifier_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_oauth_attempts_expiry_after_creation")
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name=op.f("ck_oauth_attempts_consumption_after_creation"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_attempts")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_oauth_attempts_state_hash")),
    )
    op.create_index(
        "ix_oauth_attempts_expires_at_unconsumed",
        "oauth_attempts",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )
    op.create_table(
        "oauth_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_key_version", sa.Integer(), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("token_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "token_status IN ('active', 'revoked')",
            name=op.f("ck_oauth_accounts_known_token_status"),
        ),
        sa.CheckConstraint(
            "(token_status = 'active' AND revoked_at IS NULL) OR "
            "(token_status = 'revoked' AND revoked_at IS NOT NULL)",
            name=op.f("ck_oauth_accounts_revocation_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_accounts")),
    )
    op.create_index(
        "uq_oauth_accounts_provider_subject",
        "oauth_accounts",
        ["provider", "provider_subject"],
        unique=True,
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_sessions_expiry_after_creation")
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_sessions_revocation_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(
        "ix_sessions_user_id_active",
        "sessions",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sessions_user_id_active",
        table_name="sessions",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("sessions")
    op.drop_index("uq_oauth_accounts_provider_subject", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
    op.drop_index(
        "ix_oauth_attempts_expires_at_unconsumed",
        table_name="oauth_attempts",
        postgresql_where=sa.text("consumed_at IS NULL"),
    )
    op.drop_table("oauth_attempts")
    op.drop_table("users")
