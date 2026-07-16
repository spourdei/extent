"""Public contracts for the authenticated Drive discovery workspace."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from extent_api.models import ApiModel, CoverageGap
from extent_api.query_models import WorkspaceQuestionResultView
from extent_api.source_states import WorkspaceSourceStatus

WorkspaceIngestionStatus = Literal[
    "enqueue_pending",
    "queued",
    "discovering",
    "processing",
    "ready",
    "partial",
    "failed",
    "retryable",
]
WorkspaceErrorCode = Literal[
    "authentication_required",
    "idempotency_conflict",
    "invalid_folder_url",
    "origin_rejected",
    "rate_limit_unavailable",
    "rate_limited",
    "retrieval_unavailable",
    "workspace_not_retryable",
    "workspace_not_ready",
    "workspace_not_found",
]


class CreateWorkspaceRequest(ApiModel):
    folder_url: Annotated[str, Field(min_length=1, max_length=2_048)]


class WorkspaceFolderView(ApiModel):
    drive_folder_id: Annotated[str, Field(min_length=10, max_length=200)]
    name: Annotated[str, Field(min_length=1, max_length=1_024)] | None


class WorkspaceSourceView(ApiModel):
    block_count: Annotated[int, Field(ge=0)]
    drive_file_id: Annotated[str, Field(min_length=1, max_length=200)]
    error_code: Annotated[str, Field(min_length=1, max_length=80)] | None
    extraction_method: Literal["embedded_text", "ocr"] | None
    mime_type: Annotated[str, Field(min_length=1, max_length=255)]
    name: Annotated[str, Field(min_length=1, max_length=1_024)]
    path: Annotated[list[str], Field(min_length=2, max_length=8)]
    page_count: Annotated[int, Field(ge=0)] | None
    reason_code: Annotated[str, Field(min_length=1, max_length=80)] | None
    size_bytes: Annotated[int, Field(ge=0)] | None
    status: WorkspaceSourceStatus


class WorkspaceIngestionView(ApiModel):
    capped_files: Annotated[int, Field(ge=0)]
    discovery_complete: bool
    discovered_files: Annotated[int, Field(ge=0)]
    error_code: Annotated[str, Field(min_length=1, max_length=80)] | None
    failed_files: Annotated[int, Field(ge=0)]
    finished_at: AwareDatetime | None
    folders_visited: Annotated[int, Field(ge=0)]
    gap_reasons: list[CoverageGap]
    parsing_files: Annotated[int, Field(ge=0)]
    queued_files: Annotated[int, Field(ge=0)]
    ready_files: Annotated[int, Field(ge=0)]
    run_id: UUID
    started_at: AwareDatetime | None
    status: WorkspaceIngestionStatus
    unsupported_files: Annotated[int, Field(ge=0)]


class WorkspaceView(ApiModel):
    created_at: AwareDatetime
    folder: WorkspaceFolderView
    history: Annotated[list[WorkspaceQuestionResultView], Field(max_length=20)]
    ingestion: WorkspaceIngestionView
    sources: Annotated[list[WorkspaceSourceView], Field(max_length=500)]
    workspace_id: UUID


class WorkspaceErrorView(ApiModel):
    code: WorkspaceErrorCode
    message: Annotated[str, Field(min_length=1, max_length=280)]
    reason_code: Annotated[str, Field(min_length=1, max_length=80)] | None = None
