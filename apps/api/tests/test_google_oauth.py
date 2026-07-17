"""Token-response compatibility tests for the Google OAuth adapter."""

from collections.abc import Sequence
from urllib.parse import parse_qs, urlsplit

import pytest

from extent_api.providers.google_oauth import (
    GOOGLE_DRIVE_READONLY_SCOPE,
    GOOGLE_OAUTH_SCOPES,
    GoogleOAuthError,
    GoogleOAuthProvider,
    missing_required_google_scopes,
)


class _Credentials:
    def __init__(self, *, granted_scopes: Sequence[str] | None) -> None:
        self.token = "access-token"
        self.id_token = "identity-token"
        self.refresh_token = "refresh-token"
        self.granted_scopes = granted_scopes
        self.scopes = list(GOOGLE_OAUTH_SCOPES)


class _Flow:
    def __init__(self, *, granted_scopes: Sequence[str] | None) -> None:
        self.credentials = _Credentials(granted_scopes=granted_scopes)

    def fetch_token(self, *, code: str) -> None:
        assert code == "authorization-code"


def _provider_with_flow(
    monkeypatch: pytest.MonkeyPatch, *, granted_scopes: Sequence[str] | None
) -> GoogleOAuthProvider:
    provider = GoogleOAuthProvider(client_id="client-id", client_secret="client-secret")
    flow = _Flow(granted_scopes=granted_scopes)
    monkeypatch.setattr(provider, "_flow", lambda **_: flow)
    return provider


def test_exchange_accepts_omitted_scope_as_unchanged_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_with_flow(monkeypatch, granted_scopes=None)

    tokens = provider.exchange_code(
        code="authorization-code",
        code_verifier="pkce-verifier",
        redirect_uri="https://extent.example/api/backend/v1/auth/google/callback",
    )

    assert tokens.scopes == frozenset(GOOGLE_OAUTH_SCOPES)


def test_authorization_requests_include_previously_granted_scopes() -> None:
    provider = GoogleOAuthProvider(client_id="client-id", client_secret="client-secret")

    authorization_url = provider.authorization_url(
        state="oauth-state",
        code_verifier="pkce-verifier",
        redirect_uri="https://extent.example/api/backend/v1/auth/google/callback",
    )

    query = parse_qs(urlsplit(authorization_url).query)
    assert query["include_granted_scopes"] == ["true"]


def test_exchange_rejects_explicitly_empty_scope_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_with_flow(monkeypatch, granted_scopes=[])

    with pytest.raises(GoogleOAuthError) as captured:
        provider.exchange_code(
            code="authorization-code",
            code_verifier="pkce-verifier",
            redirect_uri="https://extent.example/api/backend/v1/auth/google/callback",
        )

    assert captured.value.stage == "token_response"
    assert captured.value.reason == "granted_scopes_missing"


def test_required_scope_validation_uses_verified_id_token_for_identity() -> None:
    assert missing_required_google_scopes({GOOGLE_DRIVE_READONLY_SCOPE}) == frozenset()


def test_required_scope_validation_still_requires_drive_access() -> None:
    assert missing_required_google_scopes({"openid", "email", "profile"}) == frozenset(
        {GOOGLE_DRIVE_READONLY_SCOPE}
    )
