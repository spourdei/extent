"""Prepared, database-free query store for the public Alder Peak sample."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib.resources import files
from uuid import UUID, uuid5

from extent_api.database.identity_repository import AccountRecord, ActiveSessionRecord
from extent_api.database.query_repository import (
    ClaimRecord,
    PassageRecord,
    QueryContext,
    RetrievedBlock,
    StoredQuestionResult,
)
from extent_api.database.workspace_repository import _structured_metadata
from extent_api.models import CoverageManifest
from extent_api.providers.embeddings import Embedding
from extent_api.services.source_formats import PipelineVersion
from extent_api.services.source_ingestion import (
    parse_csv,
    parse_docx,
    parse_text_pdf,
    parse_xlsx,
)
from extent_api.token_forms import inflected_search_forms

DEMO_NAMESPACE = UUID("6ad0b89f-cf1b-4dc8-bd7f-4998b8ca12c5")
DEMO_WORKSPACE_ID = uuid5(DEMO_NAMESPACE, "workspace")
DEMO_RUN_ID = uuid5(DEMO_NAMESPACE, "run")
DEMO_FOLDER_NAME = "Alder Peak 2026 Renewal"


@dataclass(frozen=True)
class DemoSource:
    drive_file_id: str
    file_name: str
    mime_type: str
    ready: bool
    reason: str | None = None


DEMO_SOURCES = (
    DemoSource(
        "demo-alder-peak-broker-summary",
        "01_broker_renewal_summary.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        True,
    ),
    DemoSource(
        "demo-alder-peak-quote-r2",
        "02_carrier_quote_revision_2.pdf",
        "application/pdf",
        True,
    ),
    DemoSource(
        "demo-alder-peak-binder",
        "03_policy_binder.pdf",
        "application/pdf",
        True,
    ),
    DemoSource(
        "demo-alder-peak-underwriting-note",
        "04_underwriting_file_note.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        True,
    ),
    DemoSource(
        "demo-alder-peak-statement-of-values",
        "05_statement_of_values.csv",
        "text/csv",
        True,
    ),
    DemoSource(
        "demo-alder-peak-loss-runs",
        "06_loss_runs.csv",
        "text/csv",
        True,
    ),
    DemoSource(
        "demo-alder-peak-terrorism-election",
        "07_terrorism_election.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        True,
    ),
)


def demo_active_session(user_id: UUID, *, now: datetime | None = None) -> ActiveSessionRecord:
    """Build an internal principal used only to reuse the bounded query service."""

    current = now or datetime.now(UTC)
    return ActiveSessionRecord(
        account=AccountRecord(
            display_name="Public sample visitor",
            email="public-sample@extent.invalid",
            refresh_token_ciphertext=b"not-a-google-credential",
            refresh_token_key_version=1,
            scopes=(),
            token_status="active",
            user_id=user_id,
        ),
        expires_at=current + timedelta(minutes=5),
    )


class PreparedDemoQueryStore:
    """Serve the checked-in sample corpus through the live query-service protocol."""

    def __init__(self, *, user_id: UUID) -> None:
        self._user_id = user_id
        self._context = _demo_context()

    def get_context(self, *, user_id: UUID, workspace_id: UUID) -> QueryContext | None:
        if user_id != self._user_id or workspace_id != DEMO_WORKSPACE_ID:
            return None
        return self._context

    def get_by_idempotency(
        self, *, workspace_id: UUID, idempotency_key: str
    ) -> StoredQuestionResult | None:
        del idempotency_key
        if workspace_id != DEMO_WORKSPACE_ID:
            return None
        return None

    def list_results(
        self, *, user_id: UUID, workspace_id: UUID, limit: int
    ) -> list[StoredQuestionResult]:
        del limit
        if user_id != self._user_id or workspace_id != DEMO_WORKSPACE_ID:
            return []
        # Public sample questions are deliberately independent. This prevents one
        # visitor's conversation from influencing another visitor's result.
        return []

    def list_ready_blocks(self, *, context: QueryContext) -> list[RetrievedBlock]:
        if context != self._context:
            return []
        return list(_demo_blocks())

    def search_blocks(
        self,
        *,
        context: QueryContext,
        embedding: Embedding | None,
        limit: int,
        prefer_value_evidence: bool,
        structured_token_sequences: tuple[tuple[str, ...], ...],
        tokens: tuple[str, ...],
    ) -> list[RetrievedBlock]:
        del embedding
        if context != self._context or not tokens:
            return []
        scored: list[tuple[int, int, RetrievedBlock]] = []
        for ordinal, block in enumerate(_demo_blocks()):
            normalized = block.text.casefold()
            matches = sum(
                any(
                    re.search(rf"(?<!\w){re.escape(form)}(?!\w)", normalized)
                    for form in inflected_search_forms(token)
                )
                for token in tokens
            )
            structured_match = any(
                _sequence_in_text(sequence, normalized)
                for sequence in structured_token_sequences
            )
            if matches == 0 and not structured_match:
                continue
            score = matches * 10
            if structured_match:
                score += 25
            if prefer_value_evidence and block.structured_metadata is not None:
                score += 8
            scored.append((-score, ordinal, block))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [block for _, _, block in scored[:limit]]

    def store_retrieval_result(
        self,
        *,
        context: QueryContext,
        generation_status: str = "not_configured",
        idempotency_key: str,
        message: str,
        now: datetime,
        passages: tuple[PassageRecord, ...],
        question: str,
    ) -> StoredQuestionResult:
        return self._stored(
            claims=(),
            context=context,
            coverage_gap_reasons=context.gap_reasons,
            generation_status=generation_status,
            idempotency_key=idempotency_key,
            message=message,
            now=now,
            passages=passages,
            policy_version="retrieval-policy-v1",
            question=question,
            status="evidence_retrieved" if passages else "insufficient",
        )

    def store_publication_result(
        self,
        *,
        claims: tuple[ClaimRecord, ...],
        context: QueryContext,
        coverage_gap_reasons: tuple[str, ...] | None = None,
        idempotency_key: str,
        message: str,
        now: datetime,
        passages: tuple[PassageRecord, ...],
        question: str,
        status: str,
        policy_version: str = "publication-policy-v1",
    ) -> StoredQuestionResult:
        return self._stored(
            claims=claims,
            context=context,
            coverage_gap_reasons=(
                context.gap_reasons if coverage_gap_reasons is None else coverage_gap_reasons
            ),
            generation_status="completed",
            idempotency_key=idempotency_key,
            message=message,
            now=now,
            passages=passages,
            policy_version=policy_version,
            question=question,
            status=status,
        )

    def _stored(
        self,
        *,
        claims: tuple[ClaimRecord, ...],
        context: QueryContext,
        coverage_gap_reasons: tuple[str, ...],
        generation_status: str,
        idempotency_key: str,
        message: str,
        now: datetime,
        passages: tuple[PassageRecord, ...],
        policy_version: str,
        question: str,
        status: str,
    ) -> StoredQuestionResult:
        if context != self._context:
            raise LookupError("demo query context changed")
        return StoredQuestionResult(
            answer_id=uuid5(DEMO_NAMESPACE, f"answer:{idempotency_key}"),
            claims=claims,
            coverage_gap_reasons=coverage_gap_reasons,
            created_at=now,
            generation_status=generation_status,
            message=message,
            passages=passages,
            policy_version=policy_version,
            question=question,
            question_id=uuid5(DEMO_NAMESPACE, f"question:{idempotency_key}"),
            status=status,
        )


def _sequence_in_text(sequence: tuple[str, ...], normalized: str) -> bool:
    if not sequence:
        return False
    pattern = r"\s+".join(
        rf"(?:{'|'.join(re.escape(form) for form in inflected_search_forms(token))})"
        for token in sequence
    )
    return re.search(rf"(?<!\w){pattern}(?!\w)", normalized) is not None


@lru_cache(maxsize=1)
def _demo_context() -> QueryContext:
    return QueryContext(
        coverage=CoverageManifest(
            capped=0,
            discovered=7,
            discovery_complete=True,
            failed=0,
            gap_reasons=[],
            inaccessible=0,
            processing=0,
            ready=7,
            unsafe_to_parse=0,
            unknown_branches=0,
            unstable=0,
            unsupported=0,
        ),
        gap_reasons=(),
        run_id=DEMO_RUN_ID,
        run_status="ready",
        workspace_id=DEMO_WORKSPACE_ID,
    )


@lru_cache(maxsize=1)
def _demo_blocks() -> tuple[RetrievedBlock, ...]:
    corpus = files("extent_api.fixtures").joinpath("alder_peak_2026_renewal")
    blocks: list[RetrievedBlock] = []
    for source in DEMO_SOURCES:
        if not source.ready:
            continue
        content = corpus.joinpath(source.file_name).read_bytes()
        suffix = source.file_name.rsplit(".", 1)[-1]
        pipeline_version: PipelineVersion
        if suffix == "csv":
            parsed = parse_csv(content)
            pipeline_version = "csv-record-v2"
        elif suffix == "docx":
            parsed = parse_docx(content)
            pipeline_version = "docx-body-v2"
        elif suffix == "xlsx":
            parsed = parse_xlsx(content)
            pipeline_version = "xlsx-sheet-v1"
        elif suffix == "pdf":
            pdf = parse_text_pdf(content)
            pipeline_version = "pdf-page-v1"
            source_id = uuid5(DEMO_NAMESPACE, f"source:{source.file_name}")
            blocks.extend(
                RetrievedBlock(
                    block_id=uuid5(DEMO_NAMESPACE, f"block:{source.file_name}:{block.ordinal}"),
                    drive_file_id=source.drive_file_id,
                    line_start_one_based=None,
                    origin_kind="pdf_page",
                    page_index_zero_based=block.page_index_zero_based,
                    path=(DEMO_FOLDER_NAME, source.file_name),
                    printed_page_label=block.printed_page_label,
                    source_name=source.file_name,
                    source_file_id=source_id,
                    source_content_hash=pdf.content_hash,
                    structured_metadata=None,
                    pipeline_version=pipeline_version,
                    text=block.text,
                )
                for block in pdf.blocks
            )
            continue
        else:  # pragma: no cover - DEMO_SOURCES is a closed manifest.
            raise RuntimeError("prepared demo source has no parser")

        source_id = uuid5(DEMO_NAMESPACE, f"source:{source.file_name}")
        metadata = _structured_metadata(parsed, pipeline_version=pipeline_version)
        blocks.extend(
            RetrievedBlock(
                block_id=uuid5(DEMO_NAMESPACE, f"block:{source.file_name}:{block.ordinal}"),
                drive_file_id=source.drive_file_id,
                line_start_one_based=block.line_start_one_based,
                origin_kind="text_lines",
                page_index_zero_based=None,
                path=(DEMO_FOLDER_NAME, source.file_name),
                printed_page_label=None,
                source_name=source.file_name,
                source_file_id=source_id,
                source_content_hash=parsed.content_hash,
                structured_metadata=metadata if block.ordinal == 0 else None,
                pipeline_version=pipeline_version,
                text=block.text,
            )
            for block in parsed.blocks
        )
    return tuple(blocks)
