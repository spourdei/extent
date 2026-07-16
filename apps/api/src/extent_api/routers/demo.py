"""Deterministic public sample endpoints."""

from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from extent_api.models import SampleWorkspaceProjection
from extent_api.services.sample_workspace import get_sample_workspace

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


@router.get(
    "/preview",
    operation_id="get_demo_preview",
    response_model=SampleWorkspaceProjection,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    summary="Read the immutable landing-page sample",
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
    summary="Read the interactive sample workspace",
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
