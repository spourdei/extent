"""The public demo must stay queryable from the exact checked-in sample packet."""

from datetime import UTC, datetime
from uuid import UUID

from extent_api.providers.chat_completion import ModelGenerationError
from extent_api.services.demo_answer import ResilientDemoAnswerProvider
from extent_api.services.demo_corpus import (
    DEMO_WORKSPACE_ID,
    PreparedDemoQueryStore,
    _demo_blocks,
    demo_active_session,
)
from extent_api.services.query import QueryService
from extent_api.services.source_formats import (
    AdmittedSourceFormat,
    RejectedSourceFormat,
    select_source_format,
)

NOW = datetime(2026, 7, 17, 18, 0, tzinfo=UTC)
VISITOR_ID = UUID("10000000-0000-4000-8000-000000000001")


class _RateLimiter:
    def consume(self, *, now: datetime, user_id: UUID) -> None:
        assert now == NOW
        assert user_id == VISITOR_ID


class _UnavailableAnswerProvider:
    def generate(self, *, history: list[object], passages: list[object], question: str) -> None:
        del history, passages, question
        raise ModelGenerationError("provider_unavailable")


def test_exact_alder_peak_packet_is_prepared_with_xlsx_evidence() -> None:
    blocks = _demo_blocks()

    assert {block.source_name for block in blocks} == {
        "01_broker_renewal_summary.docx",
        "02_carrier_quote_revision_2.pdf",
        "03_policy_binder.pdf",
        "04_underwriting_file_note.docx",
        "05_statement_of_values.csv",
        "06_loss_runs.csv",
        "07_terrorism_election.xlsx",
    }
    spreadsheet = next(
        block for block in blocks if block.source_name == "07_terrorism_election.xlsx"
    )
    assert spreadsheet.pipeline_version == "xlsx-sheet-v1"
    assert spreadsheet.structured_metadata is not None
    assert "Annual terrorism premium\t$4,850\t2026-09-20" in spreadsheet.text


def test_public_sample_question_retrieves_spreadsheet_passage() -> None:
    service = QueryService(
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="terrorism-premium",
        question="What is the annual terrorism premium?",
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert result.status == "evidence_retrieved"
    assert any(
        passage.source_name == "07_terrorism_election.xlsx" and "$4,850" in passage.exact_quote
        for passage in result.passages
    )


def test_public_sample_publishes_extractive_answer_when_model_is_unavailable() -> None:
    service = QueryService(
        answer_provider=ResilientDemoAnswerProvider(_UnavailableAnswerProvider()),
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="terrorism-premium-fallback",
        question="What is the annual terrorism premium, and when is the election due?",
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert result.generation_status == "completed"
    assert result.status == "evidence_supported"
    assert len(result.claims) == 1
    assert "$4,850" in result.claims[0].text
    assert "2026-09-20" in result.claims[0].text
    assert result.claims[0].citations[0].source_name == "07_terrorism_election.xlsx"


def test_xlsx_is_admitted_only_with_its_real_mime_and_extension() -> None:
    admitted = select_source_format(
        name="election.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    mismatched = select_source_format(
        name="election.pdf",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert isinstance(admitted, AdmittedSourceFormat)
    assert admitted.parser_kind == "xlsx"
    assert isinstance(mismatched, RejectedSourceFormat)
    assert mismatched.reason_code == "mime_extension_conflict"
