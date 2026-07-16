"""FastAPI application factory."""

import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from extent_api import __version__
from extent_api.access_logging import install_oauth_access_log_redaction
from extent_api.config import Settings, get_settings
from extent_api.database.session import create_database_engine, create_session_factory
from extent_api.request_body_limit import (
    MAX_MUTATION_BODY_BYTES,
    MutationBodyLimitMiddleware,
)
from extent_api.routers import auth, demo, health, workspaces
from extent_api.services.sample_workspace import get_sample_workspace

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_request_logger = logging.getLogger("uvicorn.error.extent.requests")


def create_app(settings: Settings | None = None) -> FastAPI:
    install_oauth_access_log_redaction()
    runtime = settings or get_settings()
    runtime.require_runtime_capabilities()
    database_engine = create_database_engine(runtime.database_url)
    session_factory = create_session_factory(database_engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Fail startup if the checked-in projection drifts from the strict public contract.
        get_sample_workspace()
        yield
        database_engine.dispose()

    app = FastAPI(
        title=runtime.api_title,
        version=__version__,
        docs_url="/api/docs" if runtime.environment != "production" else None,
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = runtime
    app.state.session_factory = session_factory
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_headers=["Accept", "Content-Type", "Idempotency-Key"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_origins=runtime.cors_origins,
    )
    app.add_middleware(
        MutationBodyLimitMiddleware,
        maximum_bytes=MAX_MUTATION_BODY_BYTES,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=runtime.trusted_hosts)

    @app.middleware("http")
    async def request_metadata(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        started_at = perf_counter()
        supplied_request_id = request.headers.get("X-Request-Id", "")
        request_id = (
            supplied_request_id
            if _SAFE_REQUEST_ID.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception as error:
            _log_request_completion(
                request,
                duration_ms=_elapsed_milliseconds(started_at),
                exception_type=type(error).__name__,
                request_id=request_id,
                status_code=500,
            )
            raise
        if request.url.path.startswith("/api/v1/workspaces"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Request-Id"] = request_id
        _log_request_completion(
            request,
            duration_ms=_elapsed_milliseconds(started_at),
            exception_type=None,
            request_id=request_id,
            status_code=response.status_code,
        )
        return response

    app.include_router(health.router)
    app.include_router(demo.router)
    app.include_router(auth.router)
    app.include_router(workspaces.router)
    return app


def _elapsed_milliseconds(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1_000))


def _log_request_completion(
    request: Request,
    *,
    duration_ms: int,
    exception_type: str | None,
    request_id: str,
    status_code: int,
) -> None:
    route = request.scope.get("route")
    route_template = getattr(route, "path", None)
    payload: dict[str, str | int] = {
        "duration_ms": duration_ms,
        "event": "request_complete",
        "method": request.method,
        "request_id": request_id,
        "route": route_template if isinstance(route_template, str) else "unmatched",
        "status_code": status_code,
    }
    if exception_type is not None:
        payload["exception_type"] = exception_type
    level = logging.ERROR if status_code >= 500 else logging.INFO
    _request_logger.log(
        level,
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
    )


app = create_app()
