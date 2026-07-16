"""Authenticated workspace creation and owner-scoped read projections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import TypeAdapter

from extent_api.database.identity_repository import ActiveSessionRecord
from extent_api.database.models import IngestionRun, SourceFile, Workspace
from extent_api.database.query_repository import StoredQuestionResult
from extent_api.database.workspace_repository import RetryPreparation
from extent_api.models import CoverageGap
from extent_api.queueing import IngestionEnqueueError
from extent_api.services.drive_locator import (
    RejectedDriveFolderLocator,
    parse_google_drive_folder_url,
)
from extent_api.services.query import project_question_result
from extent_api.services.source_formats import PdfExtractionMethod
from extent_api.source_states import (
    FAILED_SOURCE_STATUSES,
    PENDING_SOURCE_STATUSES,
    PROCESSING_SOURCE_STATUSES,
    parse_internal_source_status,
    project_source_status,
)
from extent_api.workspace_models import (
    WorkspaceFolderView,
    WorkspaceIngestionStatus,
    WorkspaceIngestionView,
    WorkspaceSourceView,
    WorkspaceView,
)

_INGESTION_STATUS: TypeAdapter[WorkspaceIngestionStatus] = TypeAdapter(WorkspaceIngestionStatus)
_COVERAGE_GAPS: TypeAdapter[list[CoverageGap]] = TypeAdapter(list[CoverageGap])


class IngestionQueue(Protocol):
    def enqueue_run(self, run_id: UUID) -> None: ...


class WorkspaceStore(Protocol):
    def create_workspace(
        self,
        *,
        user_id: UUID,
        idempotency_key: str,
        root_folder_id: str,
        root_resource_key: str | None,
        now: datetime,
    ) -> tuple[Workspace, IngestionRun, bool]: ...

    def get_run(self, workspace_id: UUID) -> IngestionRun: ...

    def get_sources(self, run_id: UUID) -> list[SourceFile]: ...

    def get_workspace(self, *, user_id: UUID, workspace_id: UUID) -> Workspace | None: ...

    def prepare_retry(
        self, *, user_id: UUID, workspace_id: UUID
    ) -> RetryPreparation | None: ...

    def mark_enqueued(self, run_id: UUID) -> None: ...

    def mark_enqueue_failed(self, run_id: UUID, *, now: datetime) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class WorkspaceHistoryStore(Protocol):
    def list_results(
        self, *, user_id: UUID, workspace_id: UUID, limit: int
    ) -> list[StoredQuestionResult]: ...


class InvalidFolderUrl(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class WorkspaceNotRetryable(RuntimeError):
    pass


class WorkspaceService:
    def __init__(
        self,
        *,
        history_repository: WorkspaceHistoryStore,
        repository: WorkspaceStore,
        queue: IngestionQueue,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._history_repository = history_repository
        self._queue = queue
        self._clock = clock or (lambda: datetime.now(UTC))

    def create(
        self,
        *,
        active_session: ActiveSessionRecord,
        folder_url: str,
        idempotency_key: str,
    ) -> WorkspaceView:
        parsed = parse_google_drive_folder_url(folder_url)
        if isinstance(parsed, RejectedDriveFolderLocator):
            raise InvalidFolderUrl(parsed.reason_code)
        workspace, run, created = self._repository.create_workspace(
            user_id=active_session.account.user_id,
            idempotency_key=idempotency_key,
            root_folder_id=parsed.locator.folder_id,
            root_resource_key=parsed.locator.resource_key,
            now=self._clock(),
        )
        self._repository.commit()
        if created or run.status == "enqueue_pending":
            self._enqueue_pending_run(run.id)
        return self._project(
            workspace,
            self._repository.get_run(workspace.id),
            user_id=active_session.account.user_id,
        )

    def read(
        self, *, active_session: ActiveSessionRecord, workspace_id: UUID
    ) -> WorkspaceView | None:
        workspace = self._repository.get_workspace(
            user_id=active_session.account.user_id,
            workspace_id=workspace_id,
        )
        if workspace is None:
            return None
        return self._project(
            workspace,
            self._repository.get_run(workspace.id),
            user_id=active_session.account.user_id,
        )

    def retry(
        self, *, active_session: ActiveSessionRecord, workspace_id: UUID
    ) -> WorkspaceView | None:
        prepared = self._repository.prepare_retry(
            user_id=active_session.account.user_id,
            workspace_id=workspace_id,
        )
        if prepared is None:
            return None
        if not prepared.should_enqueue:
            if prepared.run.status in {"queued", "discovering", "processing"}:
                self._repository.rollback()
                return self._project(
                    prepared.workspace,
                    prepared.run,
                    user_id=active_session.account.user_id,
                )
            self._repository.rollback()
            raise WorkspaceNotRetryable
        self._repository.commit()
        self._enqueue_pending_run(prepared.run.id)
        return self._project(
            prepared.workspace,
            self._repository.get_run(prepared.workspace.id),
            user_id=active_session.account.user_id,
        )

    def _enqueue_pending_run(self, run_id: UUID) -> None:
        try:
            self._queue.enqueue_run(run_id)
        except IngestionEnqueueError:
            self._repository.rollback()
            self._repository.mark_enqueue_failed(run_id, now=self._clock())
            self._repository.commit()
            return
        self._repository.mark_enqueued(run_id)
        self._repository.commit()

    def _project(
        self, workspace: Workspace, run: IngestionRun, *, user_id: UUID
    ) -> WorkspaceView:
        sources = self._repository.get_sources(run.id)
        source_statuses = [parse_internal_source_status(source.status) for source in sources]
        return WorkspaceView(
            workspace_id=workspace.id,
            created_at=workspace.created_at,
            folder=WorkspaceFolderView(
                drive_folder_id=workspace.root_folder_id,
                name=run.root_name,
            ),
            history=[
                project_question_result(result)
                for result in self._history_repository.list_results(
                    user_id=user_id,
                    workspace_id=workspace.id,
                    limit=20,
                )
            ],
            ingestion=WorkspaceIngestionView(
                run_id=run.id,
                status=_INGESTION_STATUS.validate_python(run.status),
                discovery_complete=run.discovery_complete,
                discovered_files=run.discovered_files,
                queued_files=sum(
                    status in PENDING_SOURCE_STATUSES for status in source_statuses
                ),
                parsing_files=sum(
                    status in PROCESSING_SOURCE_STATUSES for status in source_statuses
                ),
                ready_files=source_statuses.count("ready"),
                failed_files=sum(
                    status in FAILED_SOURCE_STATUSES for status in source_statuses
                ),
                unsupported_files=run.unsupported_files,
                capped_files=run.capped_files,
                folders_visited=run.folders_visited,
                gap_reasons=_COVERAGE_GAPS.validate_python(run.gap_reasons),
                error_code=run.error_code,
                started_at=run.started_at,
                finished_at=run.finished_at,
            ),
            sources=[_source_view(source) for source in sources],
        )


def _source_view(source: SourceFile) -> WorkspaceSourceView:
    return WorkspaceSourceView(
        block_count=source.block_count,
        drive_file_id=source.drive_file_id,
        error_code=source.error_code,
        extraction_method=_pdf_extraction_method(source.pipeline_version),
        mime_type=source.mime_type,
        name=source.name,
        path=source.path,
        page_count=source.page_count,
        reason_code=source.reason_code,
        size_bytes=source.size_bytes,
        status=project_source_status(parse_internal_source_status(source.status)),
    )


def _pdf_extraction_method(
    pipeline_version: str | None,
) -> PdfExtractionMethod | None:
    if pipeline_version == "pdf-page-v1":
        return "embedded_text"
    if pipeline_version == "pdf-ocr-page-v1":
        return "ocr"
    return None
