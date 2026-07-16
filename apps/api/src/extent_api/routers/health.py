"""Process health endpoint kept outside the versioned product API."""

from fastapi import APIRouter

from extent_api import __version__
from extent_api.models import HealthResponse

router = APIRouter(tags=["operations"])


@router.get("/healthz", response_model=HealthResponse, include_in_schema=False)
@router.get(
    "/api/v1/health",
    operation_id="get_health",
    response_model=HealthResponse,
    summary="Check API liveness",
)
def health() -> HealthResponse:
    return HealthResponse(version=__version__)
