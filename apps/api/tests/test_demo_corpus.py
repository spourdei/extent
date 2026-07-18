"""The public demo must stay queryable from the exact checked-in sample packet."""

from datetime import UTC, datetime
from uuid import UUID

from extent_api.providers.chat_completion import (
    ModelConversationTurn,
    ModelGenerationError,
    ModelPassage,
)
from extent_api.services.demo_answer import ResilientDemoAnswerProvider
from extent_api.services.demo_corpus import (
    DEMO_WORKSPACE_ID,
    PreparedDemoQueryStore,
    _demo_blocks,
    demo_active_session,
)
from extent_api.services.publication import AnswerDraft, ClaimDraft, DraftEvidenceRef
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
    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft:
        del history, passages, question
        raise ModelGenerationError("provider_unavailable")


class _OneSidedAnswerProvider:
    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft:
        del history, question
        binder = next(
            passage
            for passage in passages
            if passage.source_name == "03_policy_binder.pdf"
            and "USD 146,950" in passage.exact_quote
        )
        return AnswerDraft(
            claims=[
                ClaimDraft(
                    claim_id=UUID("80000000-0000-4000-8000-000000000003"),
                    evidence=[
                        DraftEvidenceRef(
                            block_id=binder.block_id,
                            exact_quote=binder.exact_quote,
                            value="USD 146,950",
                        )
                    ],
                    relation="fact",
                    text=binder.exact_quote,
                    value="USD 146,950",
                )
            ],
            summary="The binder states USD 146,950.",
        )


class _EmptyAnswerProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft:
        del history, passages, question
        self.calls += 1
        return AnswerDraft(claims=[], summary="No answer drafted.")


class _UnverifiableComparisonProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft:
        del history, question
        self.calls += 1
        quote = next(
            passage
            for passage in passages
            if passage.source_name == "02_carrier_quote_revision_2.pdf"
            and "USD 250,000" in passage.exact_quote
        )
        binder = next(
            passage
            for passage in passages
            if passage.source_name == "03_policy_binder.pdf"
            and "USD 500,000" in passage.exact_quote
        )
        return AnswerDraft(
            claims=[
                ClaimDraft(
                    claim_id=UUID("80000000-0000-4000-8000-000000000005"),
                    evidence=[
                        DraftEvidenceRef(
                            block_id=quote.block_id,
                            exact_quote=f"{quote.exact_quote} (quote)",
                            value="USD 250,000",
                        ),
                        DraftEvidenceRef(
                            block_id=binder.block_id,
                            exact_quote=f"{binder.exact_quote} (binder)",
                            value="USD 500,000",
                        ),
                    ],
                    relation="conflict",
                    text="The quote and binder state different flood deductible minima.",
                )
            ],
            summary="The flood deductible minima differ.",
        )


class _ExplanationAnswerProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.questions: list[str] = []

    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft:
        del history
        self.calls += 1
        self.questions.append(question)
        explanation = next(
            passage
            for passage in passages
            if passage.source_name == "04_underwriting_file_note.docx"
            and "does not identify an endorsement" in passage.exact_quote
        )
        return AnswerDraft(
            claims=[
                ClaimDraft(
                    claim_id=UUID("80000000-0000-4000-8000-000000000004"),
                    evidence=[
                        DraftEvidenceRef(
                            block_id=explanation.block_id,
                            exact_quote=explanation.exact_quote,
                        )
                    ],
                    relation="fact",
                    text=explanation.exact_quote,
                )
            ],
            summary="The file provides no explanation for the premium difference.",
        )


class _EscalatingAnswerProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft:
        del history, passages, question
        self.calls += 1
        return AnswerDraft(
            canonical_question="What is the sum of Recovery across Claim_ID records?",
            claims=[],
            routing_intents=["aggregate"],
            routing_mode="structured",
            summary="This request requires a complete-data calculation.",
        )


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


def test_original_multi_scope_wording_cannot_publish_only_the_binder_value() -> None:
    service = QueryService(
        answer_provider=_OneSidedAnswerProvider(),
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="premium-comparison",
        question=(
            "What are the annual package premiums stated for quote revision 2 and the binder?"
        ),
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert result.status == "conflict"
    assert len(result.claims) == 1
    assert result.claims[0].relation == "conflict"
    assert {citation.raw_value for citation in result.claims[0].citations} == {
        "USD 144,550",
        "USD 146,950",
    }
    assert {citation.source_name for citation in result.claims[0].citations} == {
        "02_carrier_quote_revision_2.pdf",
        "03_policy_binder.pdf",
    }


def test_named_minimum_comparison_recovers_the_two_scoped_values() -> None:
    provider = _EmptyAnswerProvider()
    service = QueryService(
        answer_provider=provider,
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="flood-minimum-comparison",
        question=(
            "What flood deductible minimum is stated in quote revision 2 and the binder?"
        ),
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert provider.calls == 1
    assert result.status == "conflict"
    assert {citation.raw_value for citation in result.claims[0].citations} == {
        "USD 250,000",
        "USD 500,000",
    }
    assert {citation.source_name for citation in result.claims[0].citations} == {
        "02_carrier_quote_revision_2.pdf",
        "03_policy_binder.pdf",
    }


def test_named_comparison_recovers_after_model_citations_fail_verification() -> None:
    provider = _UnverifiableComparisonProvider()
    service = QueryService(
        answer_provider=provider,
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="flood-minimum-unverifiable-draft",
        question=(
            "What flood deductible minimum is stated in quote revision 2 and the binder?"
        ),
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert provider.calls == 1
    assert result.status == "conflict"
    assert {citation.raw_value for citation in result.claims[0].citations} == {
        "USD 250,000",
        "USD 500,000",
    }
    assert {citation.source_name for citation in result.claims[0].citations} == {
        "02_carrier_quote_revision_2.pdf",
        "03_policy_binder.pdf",
    }


def test_explanation_question_is_not_forced_into_numeric_conflict_recovery() -> None:
    provider = _ExplanationAnswerProvider()
    question = "Does the file explain the USD 2,400 premium difference?"
    service = QueryService(
        answer_provider=provider,
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="premium-explanation",
        question=question,
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert provider.calls == 1
    assert provider.questions == [question]
    assert result.status == "evidence_supported"
    assert result.claims[0].relation == "fact"
    assert "does not identify an endorsement" in result.claims[0].text


def test_broad_mismatch_question_retrieves_the_value_bearing_reconciliation_table() -> None:
    service = QueryService(
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="scheduled-term-mismatches",
        question=(
            "Which scheduled terms do not match between quote revision 2 and the binder?"
        ),
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert result.status == "evidence_retrieved"
    assert any(
        "Total annual package premium\tUSD 144,550\tUSD 146,950\tUnresolved"
        in passage.exact_quote
        and "Flood deductible minimum\tUSD 250,000\tUSD 500,000\tUnresolved"
        in passage.exact_quote
        for passage in result.passages
    )


def test_broad_mismatch_recovers_each_corroborated_field_after_model_abstention() -> None:
    provider = _EmptyAnswerProvider()
    service = QueryService(
        answer_provider=provider,
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="scheduled-term-mismatch-recovery",
        question=(
            "Which scheduled terms do not match between quote revision 2 and the binder?"
        ),
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert provider.calls == 1
    assert result.status == "conflict"
    assert {claim.text for claim in result.claims} == {
        "Total annual package premium: USD 144,550 / USD 146,950",
        "Flood deductible minimum: USD 250,000 / USD 500,000",
    }
    assert all(
        len(claim.citations) == 2
        and len({citation.source_name for citation in claim.citations}) == 2
        for claim in result.claims
    )


def test_demo_aggregate_calls_model_router_and_preserves_exact_calculation() -> None:
    provider = _EmptyAnswerProvider()
    service = QueryService(
        answer_provider=provider,
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="model-routed-recovery-total",
        question="What is the total Recovery for Claim_ID records?",
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert provider.calls == 1
    assert result.policy_version == "structured-analysis-policy-v1"
    assert result.status == "evidence_supported"
    assert [(claim.text, claim.value) for claim in result.claims] == [
        ("Sum Recovery is 16600.", "16600")
    ]
    assert [citation.line_start_one_based for citation in result.claims[0].citations] == [
        2,
        10,
    ]


def test_demo_complete_list_calls_model_router_without_three_claim_truncation() -> None:
    provider = _EmptyAnswerProvider()
    service = QueryService(
        answer_provider=provider,
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="model-routed-claim-list",
        question="List every Claim_ID",
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert provider.calls == 1
    assert [claim.value for claim in result.claims] == [
        "CLM-2301",
        "CLM-2302",
        "CLM-2303",
        "CLM-2401",
        "CLM-2402",
        "CLM-2403",
        "CLM-2501",
        "CLM-2502",
        "CLM-2503",
    ]


def test_model_can_escalate_unfamiliar_wording_into_complete_data_execution() -> None:
    provider = _EscalatingAnswerProvider()
    service = QueryService(
        answer_provider=provider,
        repository=PreparedDemoQueryStore(user_id=VISITOR_ID),
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=demo_active_session(VISITOR_ID, now=NOW),
        idempotency_key="model-escalated-recovery-total",
        question="Add up Recovery over Claim_ID entries.",
        workspace_id=DEMO_WORKSPACE_ID,
    )

    assert provider.calls == 1
    assert result.policy_version == "structured-analysis-policy-v1"
    assert result.claims[0].value == "16600"


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
