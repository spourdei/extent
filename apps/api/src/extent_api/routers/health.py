"""Process health endpoints."""

from fastapi import APIRouter

from extent_api import __version__

router = APIRouter(tags=["operations"])


@router.get("/healthz", include_in_schema=False)
@router.get("/api/v1/health", operation_id="get_health", summary="Check API liveness")
def health() -> dict[str, str]:
    return {"version": __version__}
