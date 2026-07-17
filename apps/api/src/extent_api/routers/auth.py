"""FastAPI-owned Google OAuth, session read, and disconnect endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Annotated, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session as DatabaseSession

from extent_api.auth_models import (
    AuthenticatedSessionView,
    AuthErrorView,
    GoogleAccountView,
    SessionView,
    SignedOutSessionView,
)
from extent_api.config import Settings
from extent_api.database.identity_repository import IdentityRepository
from extent_api.providers.google_oauth import GoogleOAuthError, GoogleOAuthProvider
from extent_api.security import CredentialKeyring
from extent_api.services.auth import (
    AuthService,
    InvalidOAuthState,
    OAuthCompletionError,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
logger = logging.getLogger("uvicorn.error.extent.auth")
_OAUTH_SCOPE_RETRY_COOKIE = "extent_oauth_scope_retry"


def get_database_session(request: Request) -> Iterator[DatabaseSession]:
    factory = request.app.state.session_factory
    with factory() as database_session:
        yield database_session


def get_auth_service(
    request: Request,
    database_session: Annotated[DatabaseSession, Depends(get_database_session)],
) -> AuthService | None:
    override = getattr(request.app.state, "auth_service_override", None)
    if override is not None:
        return cast(AuthService, override)

    settings: Settings = request.app.state.settings
    if not settings.google_oauth_configured:
        return None
    assert settings.google_client_id is not None
    assert settings.google_client_secret is not None
    assert settings.credential_encryption_keys is not None
    try:
        keyring = CredentialKeyring.from_config(
            settings.credential_encryption_keys.get_secret_value()
        )
        provider = GoogleOAuthProvider(
            client_id=settings.google_client_id.get_secret_value(),
            client_secret=settings.google_client_secret.get_secret_value(),
        )
    except ValueError:
        return None
    return AuthService(
        store=IdentityRepository(database_session),
        provider=provider,
        keyring=keyring,
        redirect_uri=settings.oauth_redirect_uri,
        oauth_attempt_ttl_seconds=settings.oauth_attempt_ttl_seconds,
        session_ttl_seconds=settings.session_ttl_seconds,
    )


@router.get(
    "/google/start",
    response_class=RedirectResponse,
    responses={307: {"description": "Redirect to Google's authorization endpoint"}},
)
def start_google_authorization(
    request: Request,
    service: Annotated[AuthService | None, Depends(get_auth_service)],
) -> RedirectResponse:
    settings: Settings = request.app.state.settings
    if service is None:
        return _connect_redirect(
            settings, "configuration_unavailable", reference_id=_request_id(request)
        )
    try:
        started = service.start_google_authorization()
    except GoogleOAuthError as error:
        _log_flow_failure(request, event="google_oauth_start_failed", error=error)
        return _connect_redirect(settings, "oauth_failed", reference_id=_request_id(request))
    except Exception as error:
        _log_unexpected_failure(
            request,
            event="google_oauth_start_failed",
            stage="attempt_persistence",
            error=error,
        )
        return _connect_redirect(settings, "oauth_failed", reference_id=_request_id(request))
    response = RedirectResponse(
        started.authorization_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )
    _clear_oauth_scope_retry(response, settings)
    _protect_auth_response(response)
    return response


@router.get(
    "/google/callback",
    response_class=RedirectResponse,
    responses={303: {"description": "Return to the same-origin connect surface"}},
)
def complete_google_authorization(
    request: Request,
    service: Annotated[AuthService | None, Depends(get_auth_service)],
    code: Annotated[str | None, Query(max_length=4_096)] = None,
    state_value: Annotated[str | None, Query(alias="state", max_length=256)] = None,
    provider_error: Annotated[str | None, Query(alias="error", max_length=200)] = None,
) -> RedirectResponse:
    settings: Settings = request.app.state.settings
    if service is None:
        return _connect_redirect(
            settings, "configuration_unavailable", reference_id=_request_id(request)
        )
    if state_value is None:
        return _connect_redirect(settings, "invalid_state", reference_id=_request_id(request))

    if provider_error is not None:
        try:
            service.consume_denied_authorization(state_value)
        except InvalidOAuthState:
            return _connect_redirect(
                settings, "invalid_state", reference_id=_request_id(request)
            )
        except Exception as error:
            _log_unexpected_failure(
                request,
                event="google_oauth_denial_failed",
                stage="attempt_consumption",
                error=error,
            )
            return _connect_redirect(
                settings, "oauth_failed", reference_id=_request_id(request)
            )
        result = "access_denied" if provider_error == "access_denied" else "oauth_failed"
        return _connect_redirect(settings, result)

    if code is None:
        try:
            service.consume_denied_authorization(state_value)
        except InvalidOAuthState:
            return _connect_redirect(
                settings, "invalid_state", reference_id=_request_id(request)
            )
        except Exception as error:
            _log_unexpected_failure(
                request,
                event="google_oauth_callback_failed",
                stage="attempt_consumption",
                error=error,
            )
            return _connect_redirect(
                settings, "oauth_failed", reference_id=_request_id(request)
            )
        _log_safe_failure(
            request,
            event="google_oauth_callback_failed",
            stage="callback_validation",
            reason="authorization_code_missing",
        )
        return _connect_redirect(settings, "oauth_failed", reference_id=_request_id(request))
    try:
        completed = service.complete_google_authorization(code=code, state=state_value)
    except InvalidOAuthState:
        return _connect_redirect(settings, "invalid_state", reference_id=_request_id(request))
    except (GoogleOAuthError, OAuthCompletionError) as error:
        if (
            error.reason == "required_scopes_missing"
            and request.cookies.get(_OAUTH_SCOPE_RETRY_COOKIE) != "1"
        ):
            try:
                restarted = service.start_google_authorization()
            except GoogleOAuthError as restart_error:
                _log_flow_failure(
                    request,
                    event="google_oauth_scope_retry_failed",
                    error=restart_error,
                )
            except Exception as restart_error:
                _log_unexpected_failure(
                    request,
                    event="google_oauth_scope_retry_failed",
                    stage="attempt_persistence",
                    error=restart_error,
                )
            else:
                _log_safe_failure(
                    request,
                    event="google_oauth_scope_retry_started",
                    stage=error.stage,
                    reason=error.reason,
                )
                response = RedirectResponse(
                    restarted.authorization_url,
                    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                )
                response.set_cookie(
                    key=_OAUTH_SCOPE_RETRY_COOKIE,
                    value="1",
                    max_age=settings.oauth_attempt_ttl_seconds,
                    path="/",
                    secure=settings.session_cookie_secure,
                    httponly=True,
                    samesite="lax",
                )
                _protect_auth_response(response)
                return response
        _log_flow_failure(request, event="google_oauth_callback_failed", error=error)
        response = _connect_redirect(
            settings, "oauth_failed", reference_id=_request_id(request)
        )
        _clear_oauth_scope_retry(response, settings)
        return response
    except Exception as error:
        _log_unexpected_failure(
            request,
            event="google_oauth_callback_failed",
            stage="completion",
            error=error,
        )
        return _connect_redirect(settings, "oauth_failed", reference_id=_request_id(request))

    response = _connect_redirect(settings, "success")
    response.set_cookie(
        key=settings.session_cookie_name,
        value=completed.session_token,
        max_age=settings.session_ttl_seconds,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    _clear_oauth_scope_retry(response, settings)
    return response


@router.get(
    "/session",
    response_model=SessionView,
    responses={200: {"description": "Current opaque browser-session state"}},
)
def read_session(
    request: Request,
    response: Response,
    service: Annotated[AuthService | None, Depends(get_auth_service)],
) -> SessionView:
    settings: Settings = request.app.state.settings
    _protect_auth_response(response)
    if service is None:
        return SignedOutSessionView(google_oauth_available=False)
    active = service.read_session(request.cookies.get(settings.session_cookie_name))
    if active is None:
        return SignedOutSessionView(google_oauth_available=True)
    return AuthenticatedSessionView(
        account=GoogleAccountView(
            display_name=active.account.display_name,
            email=active.account.email,
        ),
        expires_at=active.expires_at,
    )


@router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={403: {"model": AuthErrorView, "description": "Origin check failed"}},
)
def disconnect_session(
    request: Request,
    service: Annotated[AuthService | None, Depends(get_auth_service)],
) -> Response:
    settings: Settings = request.app.state.settings
    origin = request.headers.get("Origin", "").rstrip("/")
    if origin != settings.public_web_origin:
        payload = AuthErrorView(
            code="origin_rejected",
            message="This session change must come from the configured Extent origin.",
        )
        response = JSONResponse(
            payload.model_dump(mode="json", by_alias=True),
            status_code=status.HTTP_403_FORBIDDEN,
        )
        _protect_auth_response(response)
        return response
    if service is not None:
        service.disconnect(request.cookies.get(settings.session_cookie_name))
    cleared_response = Response(status_code=status.HTTP_204_NO_CONTENT)
    cleared_response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    _protect_auth_response(cleared_response)
    return cleared_response


def _connect_redirect(
    settings: Settings, result: str, *, reference_id: str | None = None
) -> RedirectResponse:
    query = {"auth": result}
    if reference_id is not None and result != "success":
        query["ref"] = reference_id
    response = RedirectResponse(
        f"{settings.connect_url}?{urlencode(query)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _protect_auth_response(response)
    return response


def _protect_auth_response(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def _clear_oauth_scope_retry(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=_OAUTH_SCOPE_RETRY_COOKIE,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _request_id(request: Request) -> str:
    return cast(str, request.state.request_id)


def _log_flow_failure(
    request: Request,
    *,
    event: str,
    error: GoogleOAuthError | OAuthCompletionError,
) -> None:
    _log_safe_failure(
        request,
        event=event,
        stage=error.stage,
        reason=error.reason,
    )


def _log_safe_failure(request: Request, *, event: str, stage: str, reason: str) -> None:
    logger.warning(
        json.dumps(
            {
                "event": event,
                "reason": reason,
                "request_id": _request_id(request),
                "stage": stage,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _log_unexpected_failure(
    request: Request, *, event: str, stage: str, error: Exception
) -> None:
    logger.error(
        json.dumps(
            {
                "event": event,
                "exception_type": type(error).__name__,
                "reason": "unexpected_error",
                "request_id": _request_id(request),
                "stage": stage,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
