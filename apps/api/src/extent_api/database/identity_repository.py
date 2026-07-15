"""Owner-scoped persistence for OAuth attempts, Google accounts, and sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DatabaseSession

from extent_api.database.models import OAuthAccount, OAuthAttempt, Session, User


@dataclass(frozen=True)
class ConsumedOAuthAttempt:
    pkce_verifier_ciphertext: bytes
    redirect_uri: str


@dataclass(frozen=True)
class AccountRecord:
    display_name: str | None
    email: str
    refresh_token_ciphertext: bytes
    refresh_token_key_version: int
    scopes: tuple[str, ...]
    token_status: str
    user_id: UUID


@dataclass(frozen=True)
class ActiveSessionRecord:
    account: AccountRecord
    expires_at: datetime


class IdentityRepository:
    def __init__(self, session: DatabaseSession) -> None:
        self._session = session

    def create_oauth_attempt(
        self,
        *,
        state_hash: bytes,
        pkce_verifier_ciphertext: bytes,
        redirect_uri: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            OAuthAttempt(
                id=uuid4(),
                state_hash=state_hash,
                pkce_verifier_ciphertext=pkce_verifier_ciphertext,
                redirect_uri=redirect_uri,
                created_at=created_at,
                expires_at=expires_at,
            )
        )

    def consume_oauth_attempt(
        self, *, state_hash: bytes, consumed_at: datetime
    ) -> ConsumedOAuthAttempt | None:
        statement = (
            update(OAuthAttempt)
            .where(
                OAuthAttempt.state_hash == state_hash,
                OAuthAttempt.consumed_at.is_(None),
                OAuthAttempt.expires_at > consumed_at,
            )
            .values(consumed_at=consumed_at)
            .returning(OAuthAttempt.pkce_verifier_ciphertext, OAuthAttempt.redirect_uri)
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return ConsumedOAuthAttempt(
            pkce_verifier_ciphertext=row.pkce_verifier_ciphertext,
            redirect_uri=row.redirect_uri,
        )

    def lock_google_subject(self, provider_subject: str) -> None:
        """Serialize first-login upserts for a Google subject inside this transaction."""

        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(f"google:{provider_subject}")))
        )

    def get_google_account(self, provider_subject: str) -> OAuthAccount | None:
        return self._session.scalar(
            select(OAuthAccount).where(
                OAuthAccount.provider == "google",
                OAuthAccount.provider_subject == provider_subject,
            )
        )

    def create_google_account(
        self,
        *,
        provider_subject: str,
        email: str,
        display_name: str | None,
        refresh_token_ciphertext: bytes,
        refresh_token_key_version: int,
        scopes: list[str],
        now: datetime,
    ) -> OAuthAccount:
        user = User(id=uuid4(), created_at=now)
        account = OAuthAccount(
            id=uuid4(),
            user_id=user.id,
            provider="google",
            provider_subject=provider_subject,
            email=email,
            display_name=display_name,
            refresh_token_ciphertext=refresh_token_ciphertext,
            refresh_token_key_version=refresh_token_key_version,
            scopes=scopes,
            token_status="active",
            created_at=now,
            updated_at=now,
        )
        self._session.add_all([user, account])
        return account

    def update_google_account(
        self,
        account: OAuthAccount,
        *,
        email: str,
        display_name: str | None,
        scopes: list[str],
        now: datetime,
        refresh_token_ciphertext: bytes | None,
        refresh_token_key_version: int | None,
    ) -> None:
        account.email = email
        account.display_name = display_name
        account.scopes = scopes
        account.updated_at = now
        account.token_status = "active"
        account.revoked_at = None
        if refresh_token_ciphertext is not None:
            assert refresh_token_key_version is not None
            account.refresh_token_ciphertext = refresh_token_ciphertext
            account.refresh_token_key_version = refresh_token_key_version

    def create_session(
        self,
        *,
        user_id: UUID,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            Session(
                id=uuid4(),
                user_id=user_id,
                token_hash=token_hash,
                created_at=created_at,
                expires_at=expires_at,
            )
        )

    def get_active_session(
        self, *, token_hash: bytes, now: datetime
    ) -> ActiveSessionRecord | None:
        row = self._session.execute(
            select(Session, OAuthAccount)
            .join(OAuthAccount, OAuthAccount.user_id == Session.user_id)
            .where(
                Session.token_hash == token_hash,
                Session.revoked_at.is_(None),
                Session.expires_at > now,
                OAuthAccount.provider == "google",
                OAuthAccount.token_status == "active",
            )
        ).one_or_none()
        if row is None:
            return None
        browser_session, account = row
        return ActiveSessionRecord(
            account=AccountRecord(
                display_name=account.display_name,
                email=account.email,
                refresh_token_ciphertext=account.refresh_token_ciphertext,
                refresh_token_key_version=account.refresh_token_key_version,
                scopes=tuple(account.scopes),
                token_status=account.token_status,
                user_id=account.user_id,
            ),
            expires_at=browser_session.expires_at,
        )

    def revoke_user_access(self, *, user_id: UUID, revoked_at: datetime) -> None:
        self._session.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        self._session.execute(
            update(OAuthAccount)
            .where(
                OAuthAccount.user_id == user_id,
                OAuthAccount.provider == "google",
                OAuthAccount.token_status == "active",
            )
            .values(token_status="revoked", revoked_at=revoked_at, updated_at=revoked_at)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
