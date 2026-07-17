"""Callback recovery tests for browser-facing OAuth routing."""

from fastapi import FastAPI
from starlette.requests import Request

from extent_api.config import Settings
from extent_api.providers.google_oauth import GoogleOAuthError
from extent_api.routers.auth import complete_google_authorization
from extent_api.services.auth import AuthorizationStart


class _MissingScopeService:
    def __init__(self) -> None:
        self.restart_count = 0

    def complete_google_authorization(self, *, code: str, state: str) -> None:
        del code, state
        raise GoogleOAuthError(
            "Google changed the requested OAuth scopes",
            stage="token_exchange",
            reason="required_scopes_missing",
        )

    def start_google_authorization(self) -> AuthorizationStart:
        self.restart_count += 1
        return AuthorizationStart("https://accounts.google.com/o/oauth2/auth?retry=1")


def _request(*, scope_retry: bool = False) -> Request:
    app = FastAPI()
    app.state.settings = Settings(
        _env_file=None,
        public_web_origin="https://extent.example",
    )
    headers = []
    if scope_retry:
        headers.append((b"cookie", b"extent_oauth_scope_retry=1"))
    request = Request(
        {
            "app": app,
            "headers": headers,
            "method": "GET",
            "path": "/api/v1/auth/google/callback",
            "query_string": b"",
            "scheme": "https",
            "server": ("extent.example", 443),
            "type": "http",
        }
    )
    request.state.request_id = "request-id"
    return request


def test_callback_restarts_authorization_once_for_partial_google_grant() -> None:
    service = _MissingScopeService()

    response = complete_google_authorization(
        request=_request(),
        service=service,  # type: ignore[arg-type]
        code="authorization-code",
        state_value="oauth-state",
        provider_error=None,
    )

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://accounts.google.com/")
    assert "extent_oauth_scope_retry=1" in response.headers["set-cookie"]
    assert service.restart_count == 1


def test_callback_stops_after_one_partial_grant_retry() -> None:
    service = _MissingScopeService()

    response = complete_google_authorization(
        request=_request(scope_retry=True),
        service=service,  # type: ignore[arg-type]
        code="authorization-code",
        state_value="oauth-state",
        provider_error=None,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "https://extent.example/connect?auth=oauth_failed&ref=request-id"
    )
    assert service.restart_count == 0
