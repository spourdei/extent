"""The single idempotent RQ ingestion entrypoint."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, Protocol
from uuid import UUID

from extent_api.config import Settings, get_settings
from extent_api.database.session import create_database_engine, create_session_factory
from extent_api.database.workspace_repository import (
    SourceProcessingRecord,
    WorkspaceRepository,
)
from extent_api.providers.embeddings import (
    Embedding,
    EmbeddingGenerationError,
    EmbeddingProvider,
    configured_embedding_provider,
    embed_texts,
)
from extent_api.providers.google_drive import create_google_drive_provider
from extent_api.providers.tesseract_ocr import TesseractPdfOcrProvider
from extent_api.security import CredentialDecryptionError, CredentialKeyring
from extent_api.services.drive_discovery import discover_drive_folder
from extent_api.services.drive_locator import DriveFolderLocator
from extent_api.services.source_formats import (
    AdmittedSourceFormat,
    ParserKind,
    PipelineVersion,
    pdf_pipeline_version_for,
    pipeline_version_for,
    select_source_format,
)
from extent_api.services.source_ingestion import (
    BinaryDownloadError,
    BinaryDownloadRequest,
    BinaryDownloadResponse,
    ParsedPdf,
    ParsedText,
    PdfExtractionError,
    PdfOcrProvider,
    SourceContentProvider,
    TextExportRequest,
    TextExtractionError,
    parse_csv,
    parse_docx,
    parse_ocr_pdf,
    parse_plain_text,
    parse_text_pdf,
    parse_xlsx,
)
from extent_api.source_states import SourceFailureStage

SOURCE_BLOCK_CAP = 1_500
logger = logging.getLogger("rq.worker.extent.ingestion")


@dataclass(frozen=True)
class SourceEmbeddingFailure:
    error_code: Literal[
        "embedding_input_invalid",
        "embedding_provider_unavailable",
        "embedding_response_invalid",
    ]
    retryable: bool


@dataclass(frozen=True)
class RunFailure:
    error_code: Literal["run_connection_failed", "unexpected_ingestion_failure"]
    retryable: bool


class PdfSourceRepository(Protocol):
    def get_admitted_pdf_ids(self, run_id: UUID) -> list[UUID]: ...

    def start_pdf_source(self, source_file_id: UUID) -> SourceProcessingRecord | None: ...

    def persist_pdf_parse(
        self,
        source_file_id: UUID,
        parsed: ParsedPdf,
        *,
        pipeline_version: PipelineVersion,
        now: datetime,
    ) -> None: ...

    def mark_source_ready(self, source_file_id: UUID) -> None: ...

    def start_source_embedding(self, source_file_id: UUID) -> None: ...

    def finish_source_embeddings(
        self, source_file_id: UUID, embeddings: Sequence[Embedding]
    ) -> None: ...

    def cap_source(self, source_file_id: UUID, *, error_code: str, now: datetime) -> None: ...

    def fail_pdf_source(
        self,
        source_file_id: UUID,
        *,
        error_code: str,
        error_stage: SourceFailureStage,
        retryable: bool,
        now: datetime,
    ) -> None: ...

    def fail_source(
        self,
        source_file_id: UUID,
        *,
        error_code: str,
        error_stage: SourceFailureStage,
        retryable: bool,
        now: datetime,
    ) -> None: ...

    def commit(self) -> None: ...


class SourceProcessingRepository(PdfSourceRepository, Protocol):
    def get_ready_source_block_count(self, run_id: UUID) -> int: ...

    def get_admitted_non_pdf_ids(self, run_id: UUID) -> list[UUID]: ...

    def start_non_pdf_source(self, source_file_id: UUID) -> SourceProcessingRecord | None: ...

    def persist_text_parse(
        self,
        source_file_id: UUID,
        parsed: ParsedText,
        *,
        pipeline_version: PipelineVersion,
        now: datetime,
    ) -> None: ...

    def finish_source_processing(self, run_id: UUID, *, now: datetime) -> None: ...


def sync_folder(run_id: str) -> None:
    """Discover one Drive folder and persist every admitted or excluded file state."""

    started_at = perf_counter()
    settings = get_settings()
    parsed_run_id = UUID(run_id)
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    outcome = "not_claimed"
    exception_type: str | None = None
    try:
        with session_factory() as database_session:
            repository = WorkspaceRepository(database_session)
            record = repository.start_discovery(parsed_run_id, now=datetime.now(UTC))
            repository.commit()
            if record is None:
                return
            if (
                settings.google_client_id is None
                or settings.google_client_secret is None
                or settings.credential_encryption_keys is None
            ):
                outcome = "oauth_configuration_missing"
                repository.mark_retryable(
                    parsed_run_id, error_code="oauth_configuration_missing"
                )
                repository.commit()
                return
            try:
                keyring = CredentialKeyring.from_config(
                    settings.credential_encryption_keys.get_secret_value()
                )
                refresh_token = keyring.decrypt(
                    record.refresh_token_ciphertext,
                    purpose="google-refresh-token",
                )
            except (CredentialDecryptionError, ValueError):
                outcome = "credential_unavailable"
                repository.mark_retryable(parsed_run_id, error_code="credential_unavailable")
                repository.commit()
                return
            provider = create_google_drive_provider(
                client_id=settings.google_client_id.get_secret_value(),
                client_secret=settings.google_client_secret.get_secret_value(),
                refresh_token=refresh_token,
            )
            result = discover_drive_folder(
                provider,
                DriveFolderLocator(
                    folder_id=record.root_folder_id,
                    kind="folder",
                    resource_key=record.root_resource_key,
                ),
            )
            repository.persist_discovery_manifest(parsed_run_id, result)
            repository.commit()
            repository.admit_discovery_manifest(parsed_run_id, result, now=datetime.now(UTC))
            repository.commit()
            if result.status == "fatal":
                outcome = "discovery_fatal"
                return
            _process_queued_sources(
                repository,
                provider,
                parsed_run_id,
                embedding_provider=_embedding_provider(settings),
                ocr_provider=TesseractPdfOcrProvider(executable=settings.ocr_executable),
            )
            outcome = "completed"
    except Exception as error:
        failure = classify_run_failure(error)
        outcome = failure.error_code
        exception_type = type(error).__name__
        with session_factory() as recovery_session:
            recovery = WorkspaceRepository(recovery_session)
            if failure.retryable:
                recovery.mark_retryable(parsed_run_id, error_code=failure.error_code)
            else:
                recovery.mark_terminal_failure(
                    parsed_run_id,
                    error_code=failure.error_code,
                    now=datetime.now(UTC),
                )
            recovery.commit()
        raise
    finally:
        payload: dict[str, str | int] = {
            "duration_ms": max(0, round((perf_counter() - started_at) * 1_000)),
            "event": "ingestion_complete",
            "outcome": outcome,
            "run_id": str(parsed_run_id),
        }
        if exception_type is not None:
            payload["exception_type"] = exception_type
        logger.log(
            logging.ERROR if exception_type is not None else logging.INFO,
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        engine.dispose()


def _process_queued_sources(
    repository: SourceProcessingRepository,
    provider: SourceContentProvider,
    run_id: UUID,
    *,
    embedding_provider: EmbeddingProvider | None,
    ocr_provider: PdfOcrProvider | None = None,
) -> None:
    remaining_blocks = max(
        0, SOURCE_BLOCK_CAP - repository.get_ready_source_block_count(run_id)
    )
    remaining_blocks = _process_queued_pdf_sources(
        repository,
        provider,
        run_id,
        embedding_provider=embedding_provider,
        ocr_provider=ocr_provider,
        remaining_blocks=remaining_blocks,
    )
    for source_file_id in repository.get_admitted_non_pdf_ids(run_id):
        source = repository.start_non_pdf_source(source_file_id)
        if source is None:
            continue
        repository.commit()
        source_format = select_source_format(name=source.name, mime_type=source.mime_type)
        if not isinstance(source_format, AdmittedSourceFormat):
            repository.fail_source(
                source_file_id,
                error_code=source_format.reason_code,
                error_stage="admission",
                retryable=False,
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        if remaining_blocks == 0:
            repository.cap_source(
                source_file_id,
                error_code="block_cap",
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        if source_format.ingestion_mode == "export_text":
            download = _export_text(
                provider,
                TextExportRequest(
                    file_id=source.drive_file_id,
                    resource_key=source.resource_key,
                ),
            )
        else:
            download = _download_binary(
                provider,
                BinaryDownloadRequest(
                    file_id=source.drive_file_id,
                    resource_key=source.resource_key,
                ),
            )
        if isinstance(download, BinaryDownloadError):
            repository.fail_source(
                source_file_id,
                error_code=download.code,
                error_stage="download",
                retryable=download.retryable,
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        try:
            parsed_text = _parse_non_pdf_evidence(
                download.content,
                parser_kind=source_format.parser_kind,
            )
        except TextExtractionError as error:
            repository.fail_source(
                source_file_id,
                error_code=error.code,
                error_stage="parse",
                retryable=False,
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        if len(parsed_text.blocks) > remaining_blocks:
            repository.cap_source(
                source_file_id,
                error_code="block_cap",
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        repository.persist_text_parse(
            source_file_id,
            parsed_text,
            pipeline_version=pipeline_version_for(source_format.parser_kind),
            now=datetime.now(UTC),
        )
        repository.commit()
        if not _embed_or_mark_ready(
            repository,
            source_file_id,
            [block.text for block in parsed_text.blocks],
            embedding_provider,
        ):
            continue
        remaining_blocks -= len(parsed_text.blocks)
    repository.finish_source_processing(run_id, now=datetime.now(UTC))
    repository.commit()


def _parse_non_pdf_evidence(content: bytes, *, parser_kind: ParserKind) -> ParsedText:
    match parser_kind:
        case "csv":
            return parse_csv(content)
        case "docx":
            return parse_docx(content)
        case "plain_text":
            return parse_plain_text(content)
        case "xlsx":
            return parse_xlsx(content)
        case "pdf":
            raise ValueError("PDF sources must use the page-aware parser path")


def _process_queued_pdf_sources(
    repository: PdfSourceRepository,
    provider: SourceContentProvider,
    run_id: UUID,
    *,
    embedding_provider: EmbeddingProvider | None,
    ocr_provider: PdfOcrProvider | None = None,
    remaining_blocks: int,
) -> int:
    for source_file_id in repository.get_admitted_pdf_ids(run_id):
        source = repository.start_pdf_source(source_file_id)
        if source is None:
            continue
        repository.commit()
        source_format = select_source_format(name=source.name, mime_type=source.mime_type)
        if (
            not isinstance(source_format, AdmittedSourceFormat)
            or source_format.parser_kind != "pdf"
        ):
            repository.fail_source(
                source_file_id,
                error_code=(
                    source_format.reason_code
                    if not isinstance(source_format, AdmittedSourceFormat)
                    else "parser_selection_mismatch"
                ),
                error_stage="admission",
                retryable=False,
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        if remaining_blocks == 0:
            repository.cap_source(
                source_file_id,
                error_code="block_cap",
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        download = _download_binary(
            provider,
            BinaryDownloadRequest(
                file_id=source.drive_file_id,
                resource_key=source.resource_key,
            ),
        )
        if isinstance(download, BinaryDownloadError):
            repository.fail_pdf_source(
                source_file_id,
                error_code=download.code,
                error_stage="download",
                retryable=download.retryable,
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        try:
            parsed = _parse_pdf_evidence(
                download.content,
                ocr_provider=ocr_provider,
            )
        except PdfExtractionError as error:
            repository.fail_pdf_source(
                source_file_id,
                error_code=error.code,
                error_stage="parse",
                retryable=error.code == "ocr_timeout",
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        if len(parsed.blocks) > remaining_blocks:
            repository.cap_source(
                source_file_id,
                error_code="block_cap",
                now=datetime.now(UTC),
            )
            repository.commit()
            continue
        repository.persist_pdf_parse(
            source_file_id,
            parsed,
            pipeline_version=pdf_pipeline_version_for(parsed.extraction_method),
            now=datetime.now(UTC),
        )
        repository.commit()
        if not _embed_or_mark_ready(
            repository,
            source_file_id,
            [block.text for block in parsed.blocks],
            embedding_provider,
        ):
            continue
        remaining_blocks -= len(parsed.blocks)
    return remaining_blocks


def _parse_pdf_evidence(
    content: bytes,
    *,
    ocr_provider: PdfOcrProvider | None,
) -> ParsedPdf:
    try:
        return parse_text_pdf(content)
    except PdfExtractionError as error:
        if error.code != "no_text" or ocr_provider is None:
            raise
    return parse_ocr_pdf(content, provider=ocr_provider)


def _embed_or_mark_ready(
    repository: PdfSourceRepository,
    source_file_id: UUID,
    texts: list[str],
    provider: EmbeddingProvider | None,
) -> bool:
    if provider is None:
        repository.mark_source_ready(source_file_id)
        repository.commit()
        return True

    repository.start_source_embedding(source_file_id)
    repository.commit()
    embeddings = _block_embeddings(provider, texts)
    if isinstance(embeddings, SourceEmbeddingFailure):
        repository.fail_source(
            source_file_id,
            error_code=embeddings.error_code,
            error_stage="embedding",
            retryable=embeddings.retryable,
            now=datetime.now(UTC),
        )
        repository.commit()
        return False
    if embeddings is None:
        raise RuntimeError("configured embedding provider returned no embeddings")
    finish_with_identity = getattr(repository, "finish_source_embeddings_with_identity", None)
    configuration_id = getattr(provider, "configuration_id", None)
    dimensions = getattr(provider, "dimensions", None)
    model = getattr(provider, "model", None)
    if (
        callable(finish_with_identity)
        and isinstance(configuration_id, str)
        and isinstance(dimensions, int)
        and isinstance(model, str)
    ):
        finish_with_identity(
            source_file_id,
            embeddings,
            configuration_id=configuration_id,
            dimensions=dimensions,
            model=model,
        )
    else:
        # Compatibility for test doubles and old repository adapters. Production
        # providers and the SQL repository always take the identity-aware branch.
        repository.finish_source_embeddings(source_file_id, embeddings)
    repository.commit()
    return True


def _embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    return configured_embedding_provider(settings)


def _block_embeddings(
    provider: EmbeddingProvider | None, texts: list[str]
) -> list[Embedding] | SourceEmbeddingFailure | None:
    if provider is None:
        return None
    try:
        return embed_texts(provider, texts)
    except EmbeddingGenerationError as error:
        if error.code == "provider_unavailable":
            return SourceEmbeddingFailure(
                error_code="embedding_provider_unavailable", retryable=True
            )
        return SourceEmbeddingFailure(error_code="embedding_response_invalid", retryable=False)
    except ValueError:
        return SourceEmbeddingFailure(error_code="embedding_input_invalid", retryable=False)


def _download_binary(
    provider: SourceContentProvider, request: BinaryDownloadRequest
) -> BinaryDownloadResponse:
    return _retry_content_request(lambda: provider.download_binary(request))


def _export_text(
    provider: SourceContentProvider, request: TextExportRequest
) -> BinaryDownloadResponse:
    return _retry_content_request(lambda: provider.export_text(request))


def _retry_content_request(
    operation: Callable[[], BinaryDownloadResponse],
) -> BinaryDownloadResponse:
    response: BinaryDownloadResponse = BinaryDownloadError(
        code="provider_failure", retryable=True
    )
    for _ in range(3):
        response = operation()
        if response.status == "ok" or not response.retryable:
            return response
    return response


def classify_run_failure(error: Exception) -> RunFailure:
    if isinstance(error, (ConnectionError, TimeoutError)):
        return RunFailure(error_code="run_connection_failed", retryable=True)
    return RunFailure(error_code="unexpected_ingestion_failure", retryable=False)
