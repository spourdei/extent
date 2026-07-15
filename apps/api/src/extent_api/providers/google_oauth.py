"""Maintained-library adapter for Google's OAuth web-server flow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from oauthlib.oauth2 import (  # type: ignore[import-untyped]
    InvalidClientError,
    InvalidGrantError,
    OAuth2Error,
)

GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_USERINFO_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
GOOGLE_USERINFO_PROFILE_SCOPE = "https://www.googleapis.com/auth/userinfo.profile"
GOOGLE_OAUTH_SCOPES = ("openid", "email", "profile", GOOGLE_DRIVE_READONLY_SCOPE)


def missing_required_google_scopes(scopes: frozenset[str] | set[str]) -> frozenset[str]:
    """Return missing capabilities while treating Google's OIDC aliases as equivalent."""

    missing: set[str] = set()
    if "openid" not in scopes:
        missing.add("openid")
    if GOOGLE_DRIVE_READONLY_SCOPE not in scopes:
        missing.add(GOOGLE_DRIVE_READONLY_SCOPE)
    if not {"email", GOOGLE_USERINFO_EMAIL_SCOPE} & scopes:
        missing.add("email")
    if not {"profile", GOOGLE_USERINFO_PROFILE_SCOPE} & scopes:
        missing.add("profile")
    return frozenset(missing)


class GoogleOAuthError(RuntimeError):
    """Sanitized provider failure; token and provider response data are never attached."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "provider",
        reason: str = "provider_failure",
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class GoogleTokenSet:
    access_token: str
    id_token: str
    refresh_token: str | None
    scopes: frozenset[str]


@dataclass(frozen=True)
class GoogleIdentity:
    display_name: str | None
    email: str
    provider_subject: str


class GoogleOAuthClient(Protocol):
    def authorization_url(
        self, *, state: str, code_verifier: str, redirect_uri: str
    ) -> str: ...

    def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> GoogleTokenSet: ...

    def verify_identity(self, tokens: GoogleTokenSet) -> GoogleIdentity: ...

    def revoke(self, refresh_token: str) -> None: ...


class GoogleOAuthProvider:
    """Google adapter with no persistence and no public token-bearing return models."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http_session: requests.Session | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("Google OAuth client credentials are required")
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http_session or requests.Session()

    def authorization_url(self, *, state: str, code_verifier: str, redirect_uri: str) -> str:
        try:
            flow = self._flow(
                state=state,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            )
            url, returned_state = flow.authorization_url(
                access_type="offline",
                prompt="consent",
            )
        except Exception as error:
            raise GoogleOAuthError(
                "Google authorization could not be started",
                stage="authorization_start",
                reason="authorization_url_failed",
            ) from error
        if returned_state != state:
            raise GoogleOAuthError(
                "Google authorization state did not round-trip",
                stage="authorization_start",
                reason="state_roundtrip_mismatch",
            )
        return str(url)

    def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> GoogleTokenSet:
        try:
            flow = self._flow(
                state=None,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
            )
            self._fetch_token_accepting_added_google_scopes(flow, code=code)
            credentials = flow.credentials
            raw_access_token = credentials.token
            raw_id_token = credentials.id_token
            raw_refresh_token = credentials.refresh_token
            granted_scopes = credentials.granted_scopes
            if not isinstance(raw_access_token, str) or not raw_access_token:
                raise GoogleOAuthError(
                    "Google did not return an access token",
                    stage="token_response",
                    reason="access_token_missing",
                )
            if not isinstance(raw_id_token, str) or not raw_id_token:
                raise GoogleOAuthError(
                    "Google did not return an identity token",
                    stage="token_response",
                    reason="id_token_missing",
                )
            if raw_refresh_token is not None and (
                not isinstance(raw_refresh_token, str) or not raw_refresh_token
            ):
                raise GoogleOAuthError(
                    "Google returned an invalid refresh token",
                    stage="token_response",
                    reason="refresh_token_invalid",
                )
            if not granted_scopes:
                raise GoogleOAuthError(
                    "Google did not report the granted scopes",
                    stage="token_response",
                    reason="granted_scopes_missing",
                )
            return GoogleTokenSet(
                access_token=raw_access_token,
                id_token=raw_id_token,
                refresh_token=raw_refresh_token,
                scopes=frozenset(granted_scopes),
            )
        except GoogleOAuthError:
            raise
        except InvalidClientError as error:
            raise GoogleOAuthError(
                "Google rejected the OAuth client authentication",
                stage="token_exchange",
                reason="invalid_client",
            ) from error
        except InvalidGrantError as error:
            raise GoogleOAuthError(
                "Google rejected the authorization grant",
                stage="token_exchange",
                reason="invalid_grant",
            ) from error
        except OAuth2Error as error:
            raise GoogleOAuthError(
                "Google rejected the OAuth token request",
                stage="token_exchange",
                reason="oauth_protocol_error",
            ) from error
        except requests.RequestException as error:
            raise GoogleOAuthError(
                "Google token exchange could not reach the provider",
                stage="token_exchange",
                reason="network_error",
            ) from error
        except Exception as error:
            raise GoogleOAuthError(
                "Google authorization code exchange failed",
                stage="token_exchange",
                reason="unexpected_exchange_error",
            ) from error

    def verify_identity(self, tokens: GoogleTokenSet) -> GoogleIdentity:
        try:
            claims = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                tokens.id_token,
                GoogleAuthRequest(session=self._http),
                audience=self._client_id,
                clock_skew_in_seconds=30,
            )
        except Exception as error:
            raise GoogleOAuthError(
                "Google identity verification failed",
                stage="identity_verification",
                reason="id_token_invalid",
            ) from error

        subject = claims.get("sub")
        email = claims.get("email")
        email_verified = claims.get("email_verified")
        display_name = claims.get("name")
        if (
            not isinstance(subject, str)
            or not subject
            or not isinstance(email, str)
            or not email
            or email_verified is not True
        ):
            raise GoogleOAuthError(
                "Google identity claims were incomplete",
                stage="identity_verification",
                reason="identity_claims_incomplete",
            )
        return GoogleIdentity(
            display_name=display_name if isinstance(display_name, str) else None,
            email=email,
            provider_subject=subject,
        )

    def revoke(self, refresh_token: str) -> None:
        try:
            response = self._http.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=5,
            )
        except requests.RequestException as error:
            raise GoogleOAuthError(
                "Google credential revocation failed",
                stage="credential_revocation",
                reason="network_error",
            ) from error
        if response.status_code >= 500:
            raise GoogleOAuthError(
                "Google credential revocation failed",
                stage="credential_revocation",
                reason="provider_unavailable",
            )

    def _fetch_token_accepting_added_google_scopes(self, flow: Flow, *, code: str) -> None:
        """Accept Google's added userinfo aliases, then validate the full grant ourselves."""

        try:
            flow.fetch_token(code=code)
        except Warning as warning:
            token = getattr(warning, "token", None)
            raw_scopes = getattr(warning, "new_scope", None)
            if (
                not isinstance(token, Mapping)
                or not isinstance(raw_scopes, (list, tuple, set, frozenset))
                or not all(isinstance(scope, str) for scope in raw_scopes)
                or bool(missing_required_google_scopes(set(raw_scopes)))
            ):
                raise GoogleOAuthError(
                    "Google changed the requested OAuth scopes",
                    stage="token_exchange",
                    reason="required_scopes_missing",
                ) from warning
            # OAuthlib raises before assigning the otherwise valid parsed token.
            # Keep the exact provider grant; later checks still enforce required scopes.
            flow.oauth2session.token = token

    def _flow(
        self,
        *,
        state: str | None,
        code_verifier: str,
        redirect_uri: str,
    ) -> Flow:
        client_config = {
            "web": {
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uris": [redirect_uri],
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=list(GOOGLE_OAUTH_SCOPES),
            state=state,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )
