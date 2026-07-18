"""Worker proofs for the per-source byte boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from extent_api import jobs
from extent_api.database.workspace_repository import SourceProcessingRecord
from extent_api.services.source_ingestion import (
    BinaryDownloadRequest,
    BinaryDownloadResponse,
    BinaryDownloadSuccess,
    TextExportRequest,
)

RUN_ID = UUID("10000000-0000-4000-8000-000000000001")
PDF_ID = UUID("20000000-0000-4000-8000-000000000001")
TEXT_ID = UUID("20000000-0000-4000-8000-000000000002")


@dataclass
class RecordingProvider:
    downloaded_file_ids: list[str] = field(default_factory=list)

    def download_binary(self, request: BinaryDownloadRequest) -> BinaryDownloadResponse:
        self.downloaded_file_ids.append(request.file_id)
        if request.file_id == "known-large-pdf":
            raise AssertionError("known oversized sources must not be downloaded")
        return BinaryDownloadSuccess(content=b"x" * 11)

    def export_text(self, request: TextExportRequest) -> BinaryDownloadResponse:
        raise AssertionError(f"unexpected text export for {request.file_id}")


@dataclass
class RecordingRepository:
    outcomes: dict[UUID, tuple[str, str]] = field(default_factory=dict)
    processing_finished: bool = False

    def get_ready_source_block_count(self, run_id: UUID) -> int:
        assert run_id == RUN_ID
        return 0

    def get_admitted_pdf_ids(self, run_id: UUID) -> list[UUID]:
        assert run_id == RUN_ID
        return [PDF_ID]

    def get_admitted_non_pdf_ids(self, run_id: UUID) -> list[UUID]:
        assert run_id == RUN_ID
        return [TEXT_ID]

    def start_pdf_source(self, source_file_id: UUID) -> SourceProcessingRecord | None:
        assert source_file_id == PDF_ID
        return SourceProcessingRecord(
            drive_file_id="known-large-pdf",
            mime_type="application/pdf",
            name="known-large.pdf",
            resource_key=None,
            size_bytes=11,
            source_file_id=source_file_id,
        )

    def start_non_pdf_source(self, source_file_id: UUID) -> SourceProcessingRecord | None:
        assert source_file_id == TEXT_ID
        return SourceProcessingRecord(
            drive_file_id="unknown-size-text",
            mime_type="text/plain",
            name="unknown-size.txt",
            resource_key=None,
            size_bytes=None,
            source_file_id=source_file_id,
        )

    def cap_source(self, source_file_id: UUID, *, error_code: str, now: datetime) -> None:
        assert now.tzinfo is not None
        self.outcomes[source_file_id] = ("capped", error_code)

    def finish_source_processing(self, run_id: UUID, *, now: datetime) -> None:
        assert run_id == RUN_ID
        assert now.tzinfo is not None
        self.processing_finished = True

    def commit(self) -> None:
        return None


def test_known_and_downloaded_oversized_sources_are_capped_without_parsing() -> None:
    repository = RecordingRepository()
    provider = RecordingProvider()

    jobs._process_queued_sources(
        repository,
        provider,
        RUN_ID,
        embedding_provider=None,
        max_source_bytes=10,
    )

    assert repository.outcomes == {
        PDF_ID: ("capped", "file_size_limit"),
        TEXT_ID: ("capped", "file_size_limit"),
    }
    assert provider.downloaded_file_ids == ["unknown-size-text"]
    assert repository.processing_finished
