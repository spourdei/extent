"""Owner-scoped persistence for Drive workspaces and discovery runs."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as DatabaseSession

from extent_api.database.models import (
    IngestionRun,
    Message,
    OAuthAccount,
    SourceBlock,
    SourceFile,
    Workspace,
)
from extent_api.providers.embeddings import EMBEDDING_DIMENSIONS, Embedding
from extent_api.services.drive_discovery import DriveDiscoveryResult
from extent_api.services.source_formats import (
    NON_PDF_INGESTION_MIME_TYPES,
    PipelineVersion,
)
from extent_api.services.source_ingestion import ParsedPdf, ParsedText
from extent_api.source_states import (
    INGESTION_PIPELINE_VERSION,
    MAX_INGESTION_ATTEMPTS,
    PENDING_SOURCE_STATUSES,
    PROCESSING_SOURCE_STATUSES,
    PUBLISHED_RUN_STATUSES,
    SourceFailureStage,
    derive_terminal_run_status,
    parse_internal_source_status,
)


@dataclass(frozen=True)
class DiscoveryJobRecord:
    refresh_token_ciphertext: bytes
    root_folder_id: str
    root_resource_key: str | None
    run_id: UUID
    user_id: UUID
    workspace_id: UUID


@dataclass(frozen=True)
class SourceProcessingRecord:
    drive_file_id: str
    mime_type: str
    name: str
    resource_key: str | None
    size_bytes: int | None
    source_file_id: UUID


@dataclass(frozen=True)
class RetryPreparation:
    should_enqueue: bool
    run: IngestionRun
    workspace: Workspace


class IdempotencyConflict(RuntimeError):
    pass


class WorkspaceRepository:
    def __init__(self, session: DatabaseSession) -> None:
        self._session = session

    def create_workspace(
        self,
        *,
        user_id: UUID,
        idempotency_key: str,
        root_folder_id: str,
        root_resource_key: str | None,
        now: datetime,
    ) -> tuple[Workspace, IngestionRun, bool]:
        existing = self._session.scalar(
            select(Workspace).where(
                Workspace.user_id == user_id,
                Workspace.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.root_folder_id != root_folder_id
                or existing.root_resource_key != root_resource_key
            ):
                raise IdempotencyConflict("idempotency key was used for another folder")
            run = self._latest_run(existing.id)
            return existing, run, False

        workspace = Workspace(
            id=uuid4(),
            user_id=user_id,
            idempotency_key=idempotency_key,
            root_folder_id=root_folder_id,
            root_resource_key=root_resource_key,
            created_at=now,
        )
        run = IngestionRun(
            id=uuid4(),
            workspace_id=workspace.id,
            status="enqueue_pending",
            attempt_count=0,
            pipeline_version=INGESTION_PIPELINE_VERSION,
            discovery_complete=False,
            discovered_files=0,
            queued_files=0,
            unsupported_files=0,
            capped_files=0,
            folders_visited=0,
            gap_reasons=[],
            policy_version="drive-traversal-policy-v1",
            created_at=now,
        )
        progress = Message(
            id=uuid4(),
            workspace_id=workspace.id,
            role="system",
            kind="progress",
            body="Folder accepted. Waiting for bounded Drive discovery.",
            ordinal=0,
            created_at=now,
        )
        self._session.add_all([workspace, run, progress])
        return workspace, run, True

    def get_workspace(self, *, user_id: UUID, workspace_id: UUID) -> Workspace | None:
        return self._session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.user_id == user_id,
            )
        )

    def get_run(self, workspace_id: UUID) -> IngestionRun:
        return self._latest_run(workspace_id)

    def get_sources(self, run_id: UUID) -> list[SourceFile]:
        return list(
            self._session.scalars(
                select(SourceFile)
                .where(SourceFile.run_id == run_id)
                .order_by(SourceFile.ordinal)
            )
        )

    def prepare_retry(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID,
    ) -> RetryPreparation | None:
        row = self._session.execute(
            select(Workspace, IngestionRun)
            .join(IngestionRun, IngestionRun.workspace_id == Workspace.id)
            .where(Workspace.id == workspace_id, Workspace.user_id == user_id)
            .order_by(IngestionRun.created_at.desc())
            .limit(1)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        workspace, run = row
        attempts_available = (
            run.attempt_count is None or run.attempt_count < MAX_INGESTION_ATTEMPTS
        )
        should_enqueue = run.status in {"enqueue_pending", "retryable"} and attempts_available
        if run.status == "retryable" and attempts_available:
            run.status = "enqueue_pending"
            run.error_code = None
            run.finished_at = None
        return RetryPreparation(
            should_enqueue=should_enqueue,
            run=run,
            workspace=workspace,
        )

    def mark_enqueued(self, run_id: UUID) -> None:
        self._session.execute(
            update(IngestionRun)
            .where(
                IngestionRun.id == run_id,
                IngestionRun.status == "enqueue_pending",
            )
            .values(status="queued")
        )

    def mark_enqueue_failed(self, run_id: UUID, *, now: datetime) -> None:
        self._session.execute(
            update(IngestionRun)
            .where(
                IngestionRun.id == run_id,
                IngestionRun.status == "enqueue_pending",
            )
            .values(
                error_code="queue_unavailable",
                finished_at=now,
                status="retryable",
            )
        )

    def start_discovery(self, run_id: UUID, *, now: datetime) -> DiscoveryJobRecord | None:
        row = self._session.execute(
            select(IngestionRun, Workspace, OAuthAccount)
            .join(Workspace, Workspace.id == IngestionRun.workspace_id)
            .outerjoin(
                OAuthAccount,
                (OAuthAccount.user_id == Workspace.user_id)
                & (OAuthAccount.provider == "google"),
            )
            .where(
                IngestionRun.id == run_id,
                IngestionRun.status.in_(("enqueue_pending", "queued")),
            )
            .with_for_update(of=IngestionRun)
        ).one_or_none()
        if row is None:
            return None
        run, workspace, account = row
        if run.pipeline_version != INGESTION_PIPELINE_VERSION:
            self._reject_unsupported_pipeline(run, now=now)
            return None
        if run.attempt_count is not None and run.attempt_count >= MAX_INGESTION_ATTEMPTS:
            self._finalize_unresolved_sources(
                run,
                error_code="retry_exhausted",
                now=now,
            )
            return None
        if account is None or account.token_status != "active":
            run.status = "retryable"
            run.error_code = "credential_unavailable"
            run.finished_at = now
            return None
        run.status = "discovering"
        if run.attempt_count is not None:
            run.attempt_count += 1
        run.started_at = now
        run.finished_at = None
        run.error_code = None
        return DiscoveryJobRecord(
            refresh_token_ciphertext=account.refresh_token_ciphertext,
            root_folder_id=workspace.root_folder_id,
            root_resource_key=workspace.root_resource_key,
            run_id=run.id,
            user_id=workspace.user_id,
            workspace_id=workspace.id,
        )

    def persist_discovery_manifest(self, run_id: UUID, result: DriveDiscoveryResult) -> None:
        run = self._session.get(IngestionRun, run_id)
        if run is None or run.status != "discovering":
            raise LookupError("ingestion run is not in discovery state")
        self._session.execute(delete(SourceFile).where(SourceFile.run_id == run_id))
        for ordinal, source in enumerate(result.sources):
            self._session.add(
                SourceFile(
                    id=uuid4(),
                    run_id=run_id,
                    drive_file_id=source.drive_file_id,
                    name=source.name,
                    mime_type=source.mime_type,
                    path=source.path,
                    status="discovered",
                    reason_code=None,
                    ingestion_mode=source.ingestion_mode,
                    resource_key=source.resource_key,
                    modified_time=source.modified_time,
                    size_bytes=source.size_bytes,
                    block_count=0,
                    ordinal=ordinal,
                )
            )
        run.status = "discovering"
        run.root_name = result.root_name
        run.discovery_complete = result.discovery_complete
        run.discovered_files = result.counts.discovered_files
        run.queued_files = 0
        run.unsupported_files = 0
        run.capped_files = 0
        run.folders_visited = result.counts.folders_visited
        run.gap_reasons = []
        run.finished_at = None
        run.error_code = None

    def admit_discovery_manifest(
        self, run_id: UUID, result: DriveDiscoveryResult, *, now: datetime
    ) -> None:
        run = self._session.get(IngestionRun, run_id)
        if run is None or run.status != "discovering":
            raise LookupError("ingestion run is not in discovery state")
        persisted_sources = {
            source.drive_file_id: source
            for source in self._session.scalars(
                select(SourceFile).where(SourceFile.run_id == run_id).with_for_update()
            )
        }
        if len(persisted_sources) != len(result.sources):
            raise RuntimeError("persisted discovery manifest does not match discovery result")
        for discovered in result.sources:
            persisted = persisted_sources.get(discovered.drive_file_id)
            if persisted is None:
                raise RuntimeError("persisted discovery manifest is missing a source")
            persisted.status = (
                "admitted" if discovered.status == "queued" else discovered.status
            )
            persisted.reason_code = discovered.reason_code

        manifest_statuses = [
            parse_internal_source_status(
                "admitted" if source.status == "queued" else source.status
            )
            for source in result.sources
        ]
        has_admitted_source = "admitted" in manifest_statuses
        if result.status == "fatal":
            run.status = "failed"
        elif has_admitted_source:
            run.status = "processing"
        else:
            run.status = derive_terminal_run_status(
                manifest_statuses,
                has_coverage_gaps=bool(result.coverage_gap_reasons),
            )
        run.queued_files = result.counts.queued
        run.unsupported_files = result.counts.unsupported
        run.capped_files = result.counts.capped
        run.gap_reasons = list(result.coverage_gap_reasons)
        run.finished_at = None if run.status == "processing" else now
        run.error_code = (
            result.gaps[0].reason_code
            if result.status == "fatal"
            else "no_ready_sources"
            if run.status == "failed"
            else None
        )

    def get_admitted_pdf_ids(self, run_id: UUID) -> list[UUID]:
        return list(
            self._session.scalars(
                select(SourceFile.id)
                .where(
                    SourceFile.run_id == run_id,
                    SourceFile.mime_type == "application/pdf",
                    SourceFile.status == "admitted",
                )
                .order_by(SourceFile.ordinal)
            )
        )

    def get_ready_pdf_page_count(self, run_id: UUID) -> int:
        page_count = self._session.scalar(
            select(func.coalesce(func.sum(SourceFile.page_count), 0)).where(
                SourceFile.run_id == run_id,
                SourceFile.mime_type == "application/pdf",
                SourceFile.status == "ready",
            )
        )
        return int(page_count or 0)

    def get_ready_source_block_count(self, run_id: UUID) -> int:
        block_count = self._session.scalar(
            select(func.count(SourceBlock.id))
            .join(SourceFile, SourceFile.id == SourceBlock.source_file_id)
            .where(
                SourceBlock.run_id == run_id,
                SourceFile.status == "ready",
            )
        )
        return int(block_count or 0)

    def get_admitted_non_pdf_ids(self, run_id: UUID) -> list[UUID]:
        return list(
            self._session.scalars(
                select(SourceFile.id)
                .where(
                    SourceFile.run_id == run_id,
                    SourceFile.mime_type.in_(NON_PDF_INGESTION_MIME_TYPES),
                    SourceFile.status == "admitted",
                )
                .order_by(SourceFile.ordinal)
            )
        )

    def start_pdf_source(self, source_file_id: UUID) -> SourceProcessingRecord | None:
        source = self._session.scalar(
            select(SourceFile)
            .where(
                SourceFile.id == source_file_id,
                SourceFile.mime_type == "application/pdf",
                SourceFile.status == "admitted",
            )
            .with_for_update()
        )
        if source is None:
            return None
        source.status = "downloading"
        source.error_code = None
        source.error_stage = None
        return SourceProcessingRecord(
            drive_file_id=source.drive_file_id,
            mime_type=source.mime_type,
            name=source.name,
            resource_key=source.resource_key,
            size_bytes=source.size_bytes,
            source_file_id=source.id,
        )

    def start_non_pdf_source(self, source_file_id: UUID) -> SourceProcessingRecord | None:
        source = self._session.scalar(
            select(SourceFile)
            .where(
                SourceFile.id == source_file_id,
                SourceFile.mime_type.in_(NON_PDF_INGESTION_MIME_TYPES),
                SourceFile.status == "admitted",
            )
            .with_for_update()
        )
        if source is None:
            return None
        source.status = "downloading"
        source.error_code = None
        source.error_stage = None
        return SourceProcessingRecord(
            drive_file_id=source.drive_file_id,
            mime_type=source.mime_type,
            name=source.name,
            resource_key=source.resource_key,
            size_bytes=source.size_bytes,
            source_file_id=source.id,
        )

    def persist_pdf_parse(
        self,
        source_file_id: UUID,
        parsed: ParsedPdf,
        *,
        pipeline_version: PipelineVersion,
        now: datetime,
    ) -> None:
        source = self._session.get(SourceFile, source_file_id)
        if source is None or source.status != "downloading":
            raise LookupError("PDF source is not in downloading state")
        run = self._session.get(IngestionRun, source.run_id)
        if run is None:
            raise LookupError("ingestion run no longer exists")
        self._session.execute(
            delete(SourceBlock).where(SourceBlock.source_file_id == source_file_id)
        )
        for block in parsed.blocks:
            self._session.add(
                SourceBlock(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    source_file_id=source.id,
                    ordinal=block.ordinal,
                    origin_kind="pdf_page",
                    page_index_zero_based=block.page_index_zero_based,
                    line_start_one_based=None,
                    printed_page_label=block.printed_page_label,
                    normalized_start=block.normalized_start,
                    normalized_end_exclusive=block.normalized_end_exclusive,
                    text=block.text,
                    embedding=None,
                    source_content_hash=parsed.content_hash,
                    normalized_content_hash=block.content_hash,
                    pipeline_version=pipeline_version,
                    structured_metadata=None,
                    created_at=now,
                )
            )
        source.status = "parsed"
        source.content_hash = parsed.content_hash
        source.pipeline_version = pipeline_version
        source.page_count = parsed.page_count
        source.block_count = len(parsed.blocks)
        source.error_code = None
        source.parsed_at = now

    def persist_text_parse(
        self,
        source_file_id: UUID,
        parsed: ParsedText,
        *,
        pipeline_version: PipelineVersion,
        now: datetime,
    ) -> None:
        source = self._session.get(SourceFile, source_file_id)
        if source is None or source.status != "downloading":
            raise LookupError("text source is not in downloading state")
        run = self._session.get(IngestionRun, source.run_id)
        if run is None:
            raise LookupError("ingestion run no longer exists")
        self._session.execute(
            delete(SourceBlock).where(SourceBlock.source_file_id == source_file_id)
        )
        for block in parsed.blocks:
            self._session.add(
                SourceBlock(
                    id=uuid4(),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    source_file_id=source.id,
                    ordinal=block.ordinal,
                    origin_kind="text_lines",
                    page_index_zero_based=None,
                    line_start_one_based=block.line_start_one_based,
                    printed_page_label=None,
                    normalized_start=block.normalized_start,
                    normalized_end_exclusive=block.normalized_end_exclusive,
                    text=block.text,
                    embedding=None,
                    source_content_hash=parsed.content_hash,
                    normalized_content_hash=block.content_hash,
                    pipeline_version=pipeline_version,
                    structured_metadata=(
                        _structured_metadata(parsed, pipeline_version=pipeline_version)
                        if block.ordinal == 0
                        else None
                    ),
                    created_at=now,
                )
            )
        source.status = "parsed"
        source.content_hash = parsed.content_hash
        source.pipeline_version = pipeline_version
        source.page_count = None
        source.block_count = len(parsed.blocks)
        source.error_code = None
        source.parsed_at = now

    def mark_source_ready(self, source_file_id: UUID) -> None:
        source = self._require_complete_source_artifacts(source_file_id, "parsed")
        source.status = "ready"

    def start_source_embedding(self, source_file_id: UUID) -> None:
        source = self._require_complete_source_artifacts(source_file_id, "parsed")
        source.status = "embedding"

    def finish_source_embeddings(
        self, source_file_id: UUID, embeddings: Sequence[Embedding]
    ) -> None:
        self._finish_source_embeddings(source_file_id, embeddings)

    def finish_source_embeddings_with_identity(
        self,
        source_file_id: UUID,
        embeddings: Sequence[Embedding],
        *,
        configuration_id: str,
        dimensions: int,
        model: str,
    ) -> None:
        """Persist vectors together with their non-secret embedding-space identity."""

        if dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("embedding dimensions do not match the database vector type")
        if len(configuration_id) != 64 or not model.strip():
            raise ValueError("embedding configuration identity is invalid")
        self._finish_source_embeddings(
            source_file_id,
            embeddings,
            configuration_id=configuration_id,
            dimensions=dimensions,
            model=model,
        )

    def _finish_source_embeddings(
        self,
        source_file_id: UUID,
        embeddings: Sequence[Embedding],
        *,
        configuration_id: str | None = None,
        dimensions: int | None = None,
        model: str | None = None,
    ) -> None:
        source = self._require_complete_source_artifacts(source_file_id, "embedding")
        blocks = list(
            self._session.scalars(
                select(SourceBlock)
                .where(SourceBlock.source_file_id == source_file_id)
                .order_by(SourceBlock.ordinal)
                .with_for_update()
            )
        )
        _validate_embeddings(len(blocks), embeddings)
        for block, embedding in zip(blocks, embeddings, strict=True):
            block.embedding = list(embedding)
            block.embedding_configuration_id = configuration_id
            block.embedding_dimensions = dimensions
            block.embedding_model = model
        source.status = "ready"

    def fail_pdf_source(
        self,
        source_file_id: UUID,
        *,
        error_code: str,
        error_stage: SourceFailureStage,
        retryable: bool,
        now: datetime,
    ) -> None:
        self.fail_source(
            source_file_id,
            error_code=error_code,
            error_stage=error_stage,
            retryable=retryable,
            now=now,
        )

    def cap_source(self, source_file_id: UUID, *, error_code: str, now: datetime) -> None:
        source = self._session.get(SourceFile, source_file_id)
        if source is None or source.status != "downloading":
            raise LookupError("source is not in a cappable processing state")
        run = self._session.get(IngestionRun, source.run_id)
        if run is None:
            raise LookupError("ingestion run no longer exists")
        source.status = "capped"
        source.error_code = error_code
        source.parsed_at = now
        source.block_count = 0
        source.page_count = None
        run.capped_files += 1
        if "capped" not in run.gap_reasons:
            run.gap_reasons = [*run.gap_reasons, "capped"]

    def fail_source(
        self,
        source_file_id: UUID,
        *,
        error_code: str,
        error_stage: SourceFailureStage,
        retryable: bool,
        now: datetime,
    ) -> None:
        source = self._session.get(SourceFile, source_file_id)
        if source is None:
            raise LookupError("source no longer exists")
        if source.status not in {"downloading", "parsed", "embedding"}:
            raise LookupError("source is not in a failable processing state")
        if source.status in {"parsed", "embedding"} and error_stage != "embedding":
            raise ValueError("parsed source failures must occur during embedding")
        if source.status == "downloading" and error_stage == "embedding":
            raise ValueError("embedding failures require parsed source artifacts")
        source.status = "retryable_failed" if retryable else "terminal_failed"
        source.error_code = error_code
        source.error_stage = error_stage
        source.parsed_at = now

    def finish_source_processing(self, run_id: UUID, *, now: datetime) -> None:
        run = self._session.get(IngestionRun, run_id)
        if run is None or run.status != "processing":
            return
        statuses = [
            parse_internal_source_status(status)
            for status in self._session.scalars(
                select(SourceFile.status).where(SourceFile.run_id == run_id)
            )
        ]
        if "retryable_failed" in statuses:
            if self._attempt_budget_exhausted(run):
                self._finalize_unresolved_sources(
                    run,
                    error_code="retry_exhausted",
                    now=now,
                )
                return
            run.status = "retryable"
            run.error_code = "source_retryable_failure"
            run.finished_at = now
            return
        if any(
            status in {"discovered", "admitted", "downloading", "parsed", "embedding"}
            for status in statuses
        ):
            run.status = "retryable"
            run.error_code = "source_processing_incomplete"
            run.finished_at = now
            return
        if "terminal_failed" in statuses and "failed" not in run.gap_reasons:
            run.gap_reasons = [*run.gap_reasons, "failed"]
        run.status = derive_terminal_run_status(
            statuses,
            has_coverage_gaps=bool(run.gap_reasons),
        )
        run.error_code = "no_ready_sources" if run.status == "failed" else None
        run.finished_at = now

    def mark_retryable(
        self, run_id: UUID, *, error_code: str, now: datetime | None = None
    ) -> None:
        run = self._session.get(IngestionRun, run_id)
        if run is None or run.status in PUBLISHED_RUN_STATUSES:
            return
        if self._attempt_budget_exhausted(run):
            self._finalize_unresolved_sources(
                run,
                error_code="retry_exhausted",
                now=now or datetime.now(UTC),
            )
            return
        run.status = "retryable"
        run.error_code = error_code
        run.finished_at = now or datetime.now(UTC)

    def mark_terminal_failure(self, run_id: UUID, *, error_code: str, now: datetime) -> None:
        run = self._session.get(IngestionRun, run_id)
        if run is None or run.status in PUBLISHED_RUN_STATUSES:
            return
        self._finalize_unresolved_sources(run, error_code=error_code, now=now)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def _attempt_budget_exhausted(self, run: IngestionRun) -> bool:
        return run.attempt_count is not None and run.attempt_count >= MAX_INGESTION_ATTEMPTS

    def _reject_unsupported_pipeline(self, run: IngestionRun, *, now: datetime) -> None:
        sources = list(
            self._session.scalars(
                select(SourceFile)
                .where(SourceFile.run_id == run.id)
                .order_by(SourceFile.ordinal)
                .with_for_update()
            )
        )
        for source in sources:
            if source.status in {"unsupported", "capped"}:
                continue
            source.status = "terminal_failed"
            source.error_code = "unsupported_ingestion_pipeline"
            source.error_stage = "admission"
            source.parsed_at = now
        if "failed" not in run.gap_reasons:
            run.gap_reasons = [*run.gap_reasons, "failed"]
        run.status = "failed"
        run.queued_files = 0
        run.error_code = "unsupported_ingestion_pipeline"
        run.finished_at = now

    def _finalize_unresolved_sources(
        self, run: IngestionRun, *, error_code: str, now: datetime
    ) -> None:
        sources = list(
            self._session.scalars(
                select(SourceFile)
                .where(SourceFile.run_id == run.id)
                .order_by(SourceFile.ordinal)
                .with_for_update()
            )
        )
        unresolved = PENDING_SOURCE_STATUSES | PROCESSING_SOURCE_STATUSES | {"retryable_failed"}
        for source in sources:
            source_status = parse_internal_source_status(source.status)
            if source_status not in unresolved:
                continue
            if source_status != "retryable_failed":
                source.error_code = error_code
                if source_status in PENDING_SOURCE_STATUSES:
                    source.error_stage = "admission"
                elif source_status == "downloading":
                    source.error_stage = "download"
                else:
                    source.error_stage = "embedding"
            source.status = "terminal_failed"
            source.parsed_at = now

        terminal_statuses = [parse_internal_source_status(source.status) for source in sources]
        if "terminal_failed" in terminal_statuses and "failed" not in run.gap_reasons:
            run.gap_reasons = [*run.gap_reasons, "failed"]
        run.status = derive_terminal_run_status(
            terminal_statuses,
            has_coverage_gaps=bool(run.gap_reasons),
        )
        run.queued_files = 0
        run.error_code = error_code if run.status == "failed" else None
        run.finished_at = now

    def _require_complete_source_artifacts(
        self,
        source_file_id: UUID,
        expected_status: Literal["parsed", "embedding"],
    ) -> SourceFile:
        source = self._session.get(SourceFile, source_file_id)
        if source is None or source.status != expected_status:
            raise LookupError(f"source is not in {expected_status} state")
        persisted_block_count = self._session.scalar(
            select(func.count(SourceBlock.id)).where(
                SourceBlock.source_file_id == source_file_id
            )
        )
        if (
            source.content_hash is None
            or source.pipeline_version is None
            or source.parsed_at is None
        ):
            raise RuntimeError("source is missing durable parse metadata")
        matching_block_count = self._session.scalar(
            select(func.count(SourceBlock.id)).where(
                SourceBlock.source_file_id == source_file_id,
                SourceBlock.source_content_hash == source.content_hash,
                SourceBlock.pipeline_version == source.pipeline_version,
            )
        )
        if (
            source.block_count <= 0
            or int(persisted_block_count or 0) != source.block_count
            or int(matching_block_count or 0) != source.block_count
        ):
            raise RuntimeError("source block set is incomplete")
        return source

    def _latest_run(self, workspace_id: UUID) -> IngestionRun:
        run = self._session.scalar(
            select(IngestionRun)
            .where(IngestionRun.workspace_id == workspace_id)
            .order_by(IngestionRun.created_at.desc())
            .limit(1)
        )
        if run is None:
            raise LookupError("workspace has no ingestion run")
        return run


def _structured_metadata(
    parsed: ParsedText, *, pipeline_version: PipelineVersion
) -> dict[str, object] | None:
    if not parsed.tables:
        return None
    serialized_tables: list[dict[str, object]] = []
    for table in parsed.tables:
        field_ids = [_normalized_field_id(header) for header in table.headers]
        duplicate_ids = {field_id for field_id in field_ids if field_ids.count(field_id) > 1}
        typed_rows = [
            [_serialized_typed_value(value) for value in row.values] for row in table.rows
        ]
        column_kinds = [
            {
                str(typed_rows[row_index][column_index]["kind"])
                for row_index in range(len(typed_rows))
                if typed_rows[row_index][column_index]["kind"] != "null"
            }
            for column_index in range(len(table.headers))
        ]
        ambiguity_codes: list[str] = []
        if duplicate_ids:
            ambiguity_codes.append("duplicate_normalized_field_identifier")
        if table.malformed_rows:
            ambiguity_codes.append("malformed_row_shape")
        if any(len(kinds) > 1 for kinds in column_kinds):
            ambiguity_codes.append("mixed_inferred_column_types")
        columns = [
            {
                "ambiguityCodes": (
                    ["duplicate_normalized_field_identifier"]
                    if field_id in duplicate_ids
                    else []
                ),
                "fieldId": field_id,
                "header": header,
                "ordinal": index,
            }
            for index, (header, field_id) in enumerate(
                zip(table.headers, field_ids, strict=True), start=1
            )
        ]
        rows = []
        for row, serialized_values in zip(table.rows, typed_rows, strict=True):
            cells = [
                {
                    "cellOrdinal": cell_ordinal,
                    "columnFieldId": field_ids[cell_ordinal - 1],
                    "lineStartOneBased": row.line_start_one_based,
                    "originalText": original,
                    "pageIndexZeroBased": None,
                    "rowOrdinal": row.ordinal,
                    "typedValue": typed,
                }
                for cell_ordinal, (original, typed) in enumerate(
                    zip(row.values, serialized_values, strict=True), start=1
                )
            ]
            rows.append(
                {
                    "cells": cells,
                    "lineStartOneBased": row.line_start_one_based,
                    "ordinal": row.ordinal,
                    # Retained for backward-compatible readers. `cells` is the
                    # authoritative typed and cell-addressable representation.
                    "values": list(row.values),
                }
            )
        serialized_tables.append(
            {
                "ambiguity": {
                    "codes": ambiguity_codes,
                    "isAmbiguous": bool(ambiguity_codes),
                },
                "columns": columns,
                "complete": table.malformed_rows == 0,
                "headers": list(table.headers),
                "malformedRows": table.malformed_rows,
                "parserVersion": pipeline_version,
                "rows": rows,
                "section": table.section,
                "sourceVersion": parsed.content_hash,
                "tableId": str(table.ordinal),
                "tableOrdinal": table.ordinal,
                "title": table.title,
            }
        )
    return {
        "parserVersion": pipeline_version,
        "schemaVersion": "structured-table-artifact-v2",
        "sourceVersion": parsed.content_hash,
        "tables": serialized_tables,
    }


def _normalized_field_id(header: str) -> str:
    normalized = unicodedata.normalize("NFKC", header).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized or "unnamed"


def _serialized_typed_value(raw: str) -> dict[str, object]:
    # Import lazily to keep the database module free of service initialization
    # cycles while ensuring persistence and execution share one inference rule.
    from extent_api.services.structured_analysis import parse_typed_value

    typed = parse_typed_value(raw)
    value = typed.value
    if hasattr(value, "isoformat"):
        safe_value: object = value.isoformat()  # type: ignore[union-attr]
    elif value is None or isinstance(value, (bool, str)):
        safe_value = value
    else:
        safe_value = str(value)
    return {
        "kind": typed.kind,
        "unit": typed.unit,
        "value": safe_value,
    }


def _validate_embeddings(expected_count: int, embeddings: Sequence[Embedding]) -> None:
    if len(embeddings) != expected_count:
        raise ValueError("embedding count must match parsed block count")
    if any(len(embedding) != EMBEDDING_DIMENSIONS for embedding in embeddings):
        raise ValueError(f"every embedding must have {EMBEDDING_DIMENSIONS} dimensions")
    if any(
        not all(isfinite(value) for value in embedding)
        or not any(value != 0 for value in embedding)
        for embedding in embeddings
    ):
        raise ValueError("every embedding must contain finite, nonzero values")
