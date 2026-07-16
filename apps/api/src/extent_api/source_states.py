"""Canonical internal source states and their public workspace projection."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, assert_never

from pydantic import TypeAdapter

InternalSourceStatus = Literal[
    "discovered",
    "admitted",
    "downloading",
    "parsed",
    "embedding",
    "ready",
    "retryable_failed",
    "terminal_failed",
    "unsupported",
    "capped",
]
WorkspaceSourceStatus = Literal["queued", "parsing", "ready", "failed", "unsupported", "capped"]
SourceFailureStage = Literal["admission", "download", "parse", "embedding"]
TerminalRunStatus = Literal["ready", "partial", "failed"]
IngestionPipelineVersion = Literal["drive-ingestion-v1"]

INGESTION_PIPELINE_VERSION: IngestionPipelineVersion = "drive-ingestion-v1"
MAX_INGESTION_ATTEMPTS = 3
PUBLISHED_RUN_STATUSES = frozenset[TerminalRunStatus]({"ready", "partial", "failed"})
PENDING_SOURCE_STATUSES = frozenset[InternalSourceStatus]({"discovered", "admitted"})
PROCESSING_SOURCE_STATUSES = frozenset[InternalSourceStatus](
    {"downloading", "parsed", "embedding"}
)
FAILED_SOURCE_STATUSES = frozenset[InternalSourceStatus](
    {"retryable_failed", "terminal_failed"}
)

_INTERNAL_SOURCE_STATUS: TypeAdapter[InternalSourceStatus] = TypeAdapter(InternalSourceStatus)


def parse_internal_source_status(value: str) -> InternalSourceStatus:
    return _INTERNAL_SOURCE_STATUS.validate_python(value)


def project_source_status(status: InternalSourceStatus) -> WorkspaceSourceStatus:
    match status:
        case "discovered" | "admitted":
            return "queued"
        case "downloading" | "parsed" | "embedding":
            return "parsing"
        case "ready":
            return "ready"
        case "retryable_failed" | "terminal_failed":
            return "failed"
        case "unsupported":
            return "unsupported"
        case "capped":
            return "capped"
        case unreachable:
            assert_never(unreachable)


def derive_terminal_run_status(
    source_statuses: Sequence[InternalSourceStatus],
    *,
    has_coverage_gaps: bool,
) -> TerminalRunStatus:
    unresolved = PENDING_SOURCE_STATUSES | PROCESSING_SOURCE_STATUSES | {"retryable_failed"}
    if any(status in unresolved for status in source_statuses):
        raise ValueError("terminal run status requires a resolved source manifest")
    ready_count = source_statuses.count("ready")
    if ready_count == 0:
        return "failed"
    if ready_count != len(source_statuses) or has_coverage_gaps:
        return "partial"
    return "ready"
