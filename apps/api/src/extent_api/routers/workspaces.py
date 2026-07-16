"""Owner-scoped task API for creating and reading Drive workspaces."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DatabaseSession

from extent_api.config import Settings
from extent_api.database.identity_repository import ActiveSessionRecord
from extent_api.database.query_repository import QueryRepository
from extent_api.database.workspace_repository import (
    IdempotencyConflict,
    WorkspaceRepository,
)
from extent_api.providers.chat_completion import ChatCompletionAnswerProvider
from extent_api.providers.embeddings import configured_embedding_provider
from extent_api.query_models import (
    AskWorkspaceQuestionRequest,
    WorkspaceQuestionResultView,
)
from extent_api.queueing import create_ingestion_queue, create_redis_connection
from extent_api.rate_limiting import (
    QueryRateExceeded,
    QueryRateLimitUnavailable,
    RedisQueryRateLimiter,
)
from extent_api.routers.auth import get_auth_service, get_database_session
from extent_api.services.auth import AuthService
from extent_api.services.query import (
    QueryService,
    RetrievalUnavailable,
    WorkspaceNotFound,
    WorkspaceNotReady,
)
from extent_api.services.workspaces import (
    InvalidFolderUrl,
    WorkspaceNotRetryable,
    WorkspaceService,
)
from extent_api.workspace_models import (
    CreateWorkspaceRequest,
    WorkspaceErrorCode,
    WorkspaceErrorView,
    WorkspaceView,
)

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def get_workspace_service(
    request: Request,
    database_session: Annotated[DatabaseSession, Depends(get_database_session)],
) -> WorkspaceService:
    override = getattr(request.app.state, "workspace_service_override", None)
    if override is not None:
        return cast(WorkspaceService, override)
    settings: Settings = request.app.state.settings
    connection = create_redis_connection(settings.redis_url)
    return WorkspaceService(
        history_repository=QueryRepository(database_session),
        repository=WorkspaceRepository(database_session),
        queue=create_ingestion_queue(connection, settings.queue_name),
    )


def get_query_service(
    request: Request,
    database_session: Annotated[DatabaseSession, Depends(get_database_session)],
) -> QueryService:
    override = getattr(request.app.state, "query_service_override", None)
    if override is not None:
        return cast(QueryService, override)
    settings: Settings = request.app.state.settings
    connection = create_redis_connection(settings.redis_url)
    answer_provider = (
        ChatCompletionAnswerProvider(
            api_key=settings.model_api_key.get_secret_value(),
            base_url=settings.model_base_url,
            model=settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
        )
        if settings.model_api_key is not None
        else None
    )
    embedding_provider = configured_embedding_provider(settings)
    return QueryService(
        answer_provider=answer_provider,
        embedding_provider=embedding_provider,
        rate_limiter=RedisQueryRateLimiter(
            connection,
            requests_per_minute=settings.query_requests_per_minute,
        ),
        repository=QueryRepository(
            database_session,
            embedding_configuration_id=(
                embedding_provider.configuration_id if embedding_provider is not None else None
            ),
        ),
    )


@router.post(
    "",
    response_model=WorkspaceView,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": WorkspaceErrorView},
        403: {"model": WorkspaceErrorView},
        409: {"model": WorkspaceErrorView},
        422: {"model": WorkspaceErrorView},
    },
)
def create_workspace(
    payload: CreateWorkspaceRequest,
    request: Request,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
    auth_service: Annotated[AuthService | None, Depends(get_auth_service)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceView | JSONResponse:
    settings: Settings = request.app.state.settings
    if request.headers.get("Origin", "").rstrip("/") != settings.public_web_origin:
        return _error(
            status.HTTP_403_FORBIDDEN,
            "origin_rejected",
            "Workspace creation must come from the configured Extent origin.",
        )
    active = _active_session(request, auth_service)
    if active is None:
        return _error(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_required",
            "Connect Google Drive before creating a workspace.",
        )
    try:
        result = service.create(
            active_session=active,
            folder_url=payload.folder_url,
            idempotency_key=idempotency_key,
        )
    except InvalidFolderUrl as error:
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_folder_url",
            "Paste a supported Google Drive folder link.",
            reason_code=error.reason_code,
        )
    except IdempotencyConflict:
        return _error(
            status.HTTP_409_CONFLICT,
            "idempotency_conflict",
            "This submission key was already used for a different folder.",
        )
    return result


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceView,
    responses={401: {"model": WorkspaceErrorView}, 404: {"model": WorkspaceErrorView}},
)
def read_workspace(
    workspace_id: UUID,
    request: Request,
    auth_service: Annotated[AuthService | None, Depends(get_auth_service)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceView | JSONResponse:
    active = _active_session(request, auth_service)
    if active is None:
        return _error(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_required",
            "Connect Google Drive to open this workspace.",
        )
    result = service.read(active_session=active, workspace_id=workspace_id)
    if result is None:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            "That workspace does not exist or is not owned by this account.",
        )
    return result


@router.post(
    "/{workspace_id}/retry",
    response_model=WorkspaceView,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": WorkspaceErrorView},
        403: {"model": WorkspaceErrorView},
        404: {"model": WorkspaceErrorView},
        409: {"model": WorkspaceErrorView},
    },
)
def retry_workspace(
    workspace_id: UUID,
    request: Request,
    auth_service: Annotated[AuthService | None, Depends(get_auth_service)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceView | JSONResponse:
    settings: Settings = request.app.state.settings
    if request.headers.get("Origin", "").rstrip("/") != settings.public_web_origin:
        return _error(
            status.HTTP_403_FORBIDDEN,
            "origin_rejected",
            "Workspace retry must come from the configured Extent origin.",
        )
    active = _active_session(request, auth_service)
    if active is None:
        return _error(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_required",
            "Connect Google Drive before retrying this workspace.",
        )
    try:
        result = service.retry(active_session=active, workspace_id=workspace_id)
    except WorkspaceNotRetryable:
        return _error(
            status.HTTP_409_CONFLICT,
            "workspace_not_retryable",
            "This workspace does not have a retryable ingestion run.",
        )
    if result is None:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            "That workspace does not exist or is not owned by this account.",
        )
    return result


@router.post(
    "/{workspace_id}/messages",
    response_model=WorkspaceQuestionResultView,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": WorkspaceErrorView},
        403: {"model": WorkspaceErrorView},
        404: {"model": WorkspaceErrorView},
        409: {"model": WorkspaceErrorView},
        429: {"model": WorkspaceErrorView},
        503: {"model": WorkspaceErrorView},
    },
)
def ask_workspace_question(
    workspace_id: UUID,
    payload: AskWorkspaceQuestionRequest,
    request: Request,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
    auth_service: Annotated[AuthService | None, Depends(get_auth_service)],
    service: Annotated[QueryService, Depends(get_query_service)],
) -> WorkspaceQuestionResultView | JSONResponse:
    settings: Settings = request.app.state.settings
    if request.headers.get("Origin", "").rstrip("/") != settings.public_web_origin:
        return _error(
            status.HTTP_403_FORBIDDEN,
            "origin_rejected",
            "Questions must come from the configured Extent origin.",
        )
    active = _active_session(request, auth_service)
    if active is None:
        return _error(
            status.HTTP_401_UNAUTHORIZED,
            "authentication_required",
            "Connect Google Drive before asking about this workspace.",
        )
    try:
        return service.ask(
            active_session=active,
            idempotency_key=idempotency_key,
            question=payload.question,
            workspace_id=workspace_id,
        )
    except WorkspaceNotFound:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            "That workspace does not exist or is not owned by this account.",
        )
    except WorkspaceNotReady:
        return _error(
            status.HTTP_409_CONFLICT,
            "workspace_not_ready",
            "Wait for evidence preparation to finish before asking a question.",
        )
    except RetrievalUnavailable:
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "retrieval_unavailable",
            "Evidence retrieval is temporarily unavailable. Try the question again.",
        )
    except QueryRateExceeded as error:
        response = _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many questions were submitted. Wait briefly and try again.",
        )
        response.headers["Retry-After"] = str(error.retry_after_seconds)
        return response
    except QueryRateLimitUnavailable:
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "rate_limit_unavailable",
            "Question admission is temporarily unavailable. Try again shortly.",
        )
    except ValueError:
        return _error(
            status.HTTP_409_CONFLICT,
            "idempotency_conflict",
            "This submission key was already used for a different question.",
        )


def _active_session(
    request: Request, auth_service: AuthService | None
) -> ActiveSessionRecord | None:
    if auth_service is None:
        return None
    settings: Settings = request.app.state.settings
    return auth_service.read_session(request.cookies.get(settings.session_cookie_name))


def _error(
    status_code: int,
    code: WorkspaceErrorCode,
    message: str,
    *,
    reason_code: str | None = None,
) -> JSONResponse:
    payload = WorkspaceErrorView(
        code=code,
        message=message,
        reason_code=reason_code,
    )
    response = JSONResponse(
        payload.model_dump(mode="json", by_alias=True), status_code=status_code
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response
