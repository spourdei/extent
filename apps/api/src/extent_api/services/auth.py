"""Google OAuth and opaque-session orchestration with deterministic security checks."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from extent_api.database.identity_repository import (
    ActiveSessionRecord,
    ConsumedOAuthAttempt,
)
from extent_api.database.models import OAuthAccount
from extent_api.providers.google_oauth import (
    GoogleOAuthClient,
    GoogleOAuthError,
    missing_required_google_scopes,
)
from extent_api.security import (
    CredentialDecryptionError,
    CredentialKeyring,
    hash_secret,
    random_urlsafe_token,
)


class AuthConfigurationError(RuntimeError):
    pass


class InvalidOAuthState(RuntimeError):
    pass


class OAuthCompletionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str = "completion",
        reason: str = "completion_failed",
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason = reason


class GoogleAccountStore(Protocol):
    def create_oauth_attempt(
        self,
        *,
        state_hash: bytes,
        pkce_verifier_ciphertext: bytes,
        redirect_uri: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    def consume_oauth_attempt(
        self, *, state_hash: bytes, consumed_at: datetime
    ) -> ConsumedOAuthAttempt | None: ...

    def lock_google_subject(self, provider_subject: str) -> None: ...

    def get_google_account(self, provider_subject: str) -> OAuthAccount | None: ...

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
    ) -> OAuthAccount: ...

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
    ) -> None: ...

    def create_session(
        self,
        *,
        user_id: UUID,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    def get_active_session(
        self, *, token_hash: bytes, now: datetime
    ) -> ActiveSessionRecord | None: ...

    def revoke_user_access(self, *, user_id: UUID, revoked_at: datetime) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True)
class AuthorizationStart:
    authorization_url: str


@dataclass(frozen=True)
class CompletedLogin:
    expires_at: datetime
    session_token: str


class AuthService:
    def __init__(
        self,
        *,
        store: GoogleAccountStore,
        provider: GoogleOAuthClient,
        keyring: CredentialKeyring,
        redirect_uri: str,
        oauth_attempt_ttl_seconds: int,
        session_ttl_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._keyring = keyring
        self._redirect_uri = redirect_uri
        self._oauth_attempt_ttl = timedelta(seconds=oauth_attempt_ttl_seconds)
        self._session_ttl = timedelta(seconds=session_ttl_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def start_google_authorization(self) -> AuthorizationStart:
        now = self._clock()
        state = random_urlsafe_token(32)
        verifier = random_urlsafe_token(64)
        authorization_url = self._provider.authorization_url(
            state=state,
            code_verifier=verifier,
            redirect_uri=self._redirect_uri,
        )
        encrypted_verifier = self._keyring.encrypt(verifier, purpose="oauth-pkce")
        try:
            self._store.create_oauth_attempt(
                state_hash=hash_secret(state),
                pkce_verifier_ciphertext=encrypted_verifier.ciphertext,
                redirect_uri=self._redirect_uri,
                created_at=now,
                expires_at=now + self._oauth_attempt_ttl,
            )
            self._store.commit()
        except Exception:
            self._store.rollback()
            raise
        return AuthorizationStart(authorization_url=authorization_url)

    def consume_denied_authorization(self, state: str) -> None:
        self._consume_attempt(state)

    def complete_google_authorization(self, *, code: str, state: str) -> CompletedLogin:
        attempt = self._consume_attempt(state)
        try:
            verifier = self._keyring.decrypt(
                attempt.pkce_verifier_ciphertext, purpose="oauth-pkce"
            )
        except CredentialDecryptionError as error:
            raise OAuthCompletionError(
                "OAuth attempt could not be resumed",
                stage="attempt_resume",
                reason="pkce_decryption_failed",
            ) from error

        tokens = self._provider.exchange_code(
            code=code,
            code_verifier=verifier,
            redirect_uri=attempt.redirect_uri,
        )
        if missing_required_google_scopes(tokens.scopes):
            raise OAuthCompletionError(
                "Google did not grant the required scopes",
                stage="scope_validation",
                reason="required_scopes_missing",
            )
        identity = self._provider.verify_identity(tokens)
        now = self._clock()
        encrypted_refresh = (
            self._keyring.encrypt(tokens.refresh_token, purpose="google-refresh-token")
            if tokens.refresh_token is not None
            else None
        )

        try:
            self._store.lock_google_subject(identity.provider_subject)
            account = self._store.get_google_account(identity.provider_subject)
            if account is None:
                if encrypted_refresh is None:
                    raise OAuthCompletionError(
                        "Google did not return the refresh credential required "
                        "for a new account",
                        stage="credential_validation",
                        reason="new_account_refresh_token_missing",
                    )
                account = self._store.create_google_account(
                    provider_subject=identity.provider_subject,
                    email=identity.email,
                    display_name=identity.display_name,
                    refresh_token_ciphertext=encrypted_refresh.ciphertext,
                    refresh_token_key_version=encrypted_refresh.key_version,
                    scopes=sorted(tokens.scopes),
                    now=now,
                )
            else:
                if account.token_status == "revoked" and encrypted_refresh is None:
                    raise OAuthCompletionError(
                        "Google did not return a new refresh credential for "
                        "the disconnected account",
                        stage="credential_validation",
                        reason="reconnect_refresh_token_missing",
                    )
                self._store.update_google_account(
                    account,
                    email=identity.email,
                    display_name=identity.display_name,
                    scopes=sorted(tokens.scopes),
                    now=now,
                    refresh_token_ciphertext=(
                        encrypted_refresh.ciphertext if encrypted_refresh else None
                    ),
                    refresh_token_key_version=(
                        encrypted_refresh.key_version if encrypted_refresh else None
                    ),
                )

            session_token = random_urlsafe_token(32)
            expires_at = now + self._session_ttl
            self._store.create_session(
                user_id=account.user_id,
                token_hash=hash_secret(session_token),
                created_at=now,
                expires_at=expires_at,
            )
            self._store.commit()
        except OAuthCompletionError:
            self._store.rollback()
            raise
        except Exception as error:
            self._store.rollback()
            raise OAuthCompletionError(
                "Google account could not be persisted",
                stage="persistence",
                reason="account_persistence_failed",
            ) from error
        return CompletedLogin(session_token=session_token, expires_at=expires_at)

    def read_session(self, session_token: str | None) -> ActiveSessionRecord | None:
        if not session_token or len(session_token) > 256:
            return None
        return self._store.get_active_session(
            token_hash=hash_secret(session_token), now=self._clock()
        )

    def disconnect(self, session_token: str | None) -> None:
        active = self.read_session(session_token)
        if active is None:
            return
        try:
            refresh_token = self._keyring.decrypt(
                active.account.refresh_token_ciphertext,
                purpose="google-refresh-token",
            )
        except CredentialDecryptionError:
            refresh_token = None

        try:
            self._store.revoke_user_access(
                user_id=active.account.user_id, revoked_at=self._clock()
            )
            self._store.commit()
        except Exception:
            self._store.rollback()
            raise

        if refresh_token is not None:
            # Local access is already removed; provider revocation is best effort here.
            with suppress(GoogleOAuthError):
                self._provider.revoke(refresh_token)

    def _consume_attempt(self, state: str) -> ConsumedOAuthAttempt:
        if not state or len(state) > 256:
            raise InvalidOAuthState("OAuth state is invalid or expired")
        now = self._clock()
        try:
            attempt = self._store.consume_oauth_attempt(
                state_hash=hash_secret(state), consumed_at=now
            )
            self._store.commit()
        except Exception:
            self._store.rollback()
            raise
        if attempt is None:
            raise InvalidOAuthState("OAuth state is invalid or expired")
        return attempt
