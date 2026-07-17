"""Token-response compatibility tests for the Google OAuth adapter."""

from collections.abc import Sequence

import pytest

from extent_api.providers.google_oauth import (
    GOOGLE_OAUTH_SCOPES,
    GoogleOAuthError,
    GoogleOAuthProvider,
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
