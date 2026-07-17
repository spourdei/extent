"""Prepared public sample endpoints, including bounded anonymous questions."""

import ipaddress
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid5

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse

from extent_api.config import Settings
from extent_api.models import SampleWorkspaceProjection
from extent_api.providers.chat_completion import ChatCompletionAnswerProvider
from extent_api.query_models import AskWorkspaceQuestionRequest, WorkspaceQuestionResultView
from extent_api.queueing import create_redis_connection
from extent_api.rate_limiting import (
    QueryRateExceeded,
    QueryRateLimitUnavailable,
    RedisQueryRateLimiter,
)
from extent_api.services.demo_answer import ResilientDemoAnswerProvider
from extent_api.services.demo_corpus import (
    DEMO_NAMESPACE,
    DEMO_WORKSPACE_ID,
    PreparedDemoQueryStore,
    demo_active_session,
)
from extent_api.services.query import QueryService, RetrievalUnavailable
from extent_api.services.sample_workspace import get_sample_workspace
from extent_api.workspace_models import WorkspaceErrorCode, WorkspaceErrorView

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
_DEMO_GLOBAL_RATE_ID = uuid5(DEMO_NAMESPACE, "global-rate-limit")


@router.get(
    "/preview",
    operation_id="get_demo_preview",
    response_model=SampleWorkspaceProjection,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="Read the prepared Alder Peak landing-page sample",
)
def preview(response: Response) -> SampleWorkspaceProjection:
    response.headers["Cache-Control"] = "public, max-age=300, immutable"
    return get_sample_workspace()


@router.get(
    "/workspace",
    operation_id="get_demo_workspace",
    response_model=SampleWorkspaceProjection,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="Read the interactive Alder Peak sample workspace",
)
def workspace(
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> SampleWorkspaceProjection:
    # The parameter is accepted deliberately so a future persisted demo can add ETags without
    # changing the route signature. It is not trusted as state or replay authority.
    del if_none_match
    response.headers["Cache-Control"] = "no-store"
    return get_sample_workspace()


@router.post(
    "/questions",
    operation_id="ask_demo_question",
    response_model=WorkspaceQuestionResultView,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"model": WorkspaceErrorView},
        429: {"model": WorkspaceErrorView},
        503: {"model": WorkspaceErrorView},
    },
    summary="Ask an anonymous question about the prepared sample",
)
def ask_question(
    payload: AskWorkspaceQuestionRequest,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
) -> WorkspaceQuestionResultView | JSONResponse:
    settings: Settings = request.app.state.settings
    if request.headers.get("Origin", "").rstrip("/") != settings.public_web_origin:
        return _error(
            status.HTTP_403_FORBIDDEN,
            "origin_rejected",
            "Sample questions must come from the configured Extent origin.",
        )

    now = datetime.now(UTC)
    visitor_id = _visitor_id(request)
    external_answer_provider = (
        ChatCompletionAnswerProvider(
            api_key=settings.model_api_key.get_secret_value(),
            base_url=settings.model_base_url,
            model=settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
        )
        if settings.model_api_key is not None
        else None
    )
    redis = create_redis_connection(settings.redis_url)
    service = QueryService(
        answer_provider=ResilientDemoAnswerProvider(external_answer_provider),
        clock=lambda: now,
        embedding_provider=None,
        rate_limiter=_DemoRateLimiter(
            per_visitor=RedisQueryRateLimiter(
                redis,
                requests_per_minute=settings.query_requests_per_minute,
            ),
            global_limit=RedisQueryRateLimiter(redis, requests_per_minute=60),
        ),
        repository=PreparedDemoQueryStore(user_id=visitor_id),
    )
    try:
        result = service.ask(
            active_session=demo_active_session(visitor_id, now=now),
            idempotency_key=idempotency_key,
            question=payload.question,
            workspace_id=DEMO_WORKSPACE_ID,
        )
    except QueryRateExceeded as error:
        response = _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many sample questions were submitted. Wait briefly and try again.",
        )
        response.headers["Retry-After"] = str(error.retry_after_seconds)
        return response
    except QueryRateLimitUnavailable:
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "rate_limit_unavailable",
            "Sample question admission is temporarily unavailable. Try again shortly.",
        )
    except RetrievalUnavailable:
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "retrieval_unavailable",
            "Extent could not search the prepared sample right now. Try again.",
        )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return result


def _visitor_id(request: Request) -> UUID:
    """Hash a short-lived network fingerprint without retaining the source address."""

    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    fallback = request.client.host if request.client is not None else "unknown"
    candidate = forwarded or fallback
    try:
        address = ipaddress.ip_address(candidate).compressed
    except ValueError:
        address = "unknown"
    return uuid5(DEMO_NAMESPACE, f"visitor:{address}")


class _DemoRateLimiter:
    def __init__(
        self,
        *,
        per_visitor: RedisQueryRateLimiter,
        global_limit: RedisQueryRateLimiter,
    ) -> None:
        self._per_visitor = per_visitor
        self._global_limit = global_limit

    def consume(self, *, now: datetime, user_id: UUID) -> None:
        self._per_visitor.consume(now=now, user_id=user_id)
        self._global_limit.consume(now=now, user_id=_DEMO_GLOBAL_RATE_ID)


def _error(status_code: int, code: WorkspaceErrorCode, message: str) -> JSONResponse:
    payload = WorkspaceErrorView(code=code, message=message)
    response = JSONResponse(
        payload.model_dump(mode="json", by_alias=True), status_code=status_code
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response
