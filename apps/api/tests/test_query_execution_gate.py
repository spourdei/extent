"""Focused regressions for query routing at the structured execution boundary."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

from extent_api.database.identity_repository import AccountRecord, ActiveSessionRecord
from extent_api.database.query_repository import (
    ClaimRecord,
    PassageRecord,
    QueryContext,
    RetrievedBlock,
    StoredQuestionResult,
)
from extent_api.models import CoverageManifest
from extent_api.providers.chat_completion import ModelConversationTurn, ModelPassage
from extent_api.services.publication import AnswerDraft, ClaimDraft, DraftEvidenceRef
from extent_api.services.query import QueryService
from extent_api.services.structured_analysis import (
    ReconciliationAudit,
    StructuredAnalysisResult,
)

NOW = datetime(2026, 7, 17, 12, 30, tzinfo=UTC)
USER_ID = UUID("10000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-4000-8000-000000000001")
RUN_ID = UUID("30000000-0000-4000-8000-000000000001")
SOURCE_ID = UUID("40000000-0000-4000-8000-000000000001")
BLOCK_ID = UUID("50000000-0000-4000-8000-000000000001")
QUESTION_ID = UUID("60000000-0000-4000-8000-000000000001")
ANSWER_ID = UUID("70000000-0000-4000-8000-000000000001")


class _RateLimiter:
    def consume(self, *, now: datetime, user_id: UUID) -> None:
        assert now == NOW
        assert user_id == USER_ID


class _QueryStore:
    def __init__(self) -> None:
        self.context = QueryContext(
            coverage=CoverageManifest(
                capped=0,
                discovered=1,
                discovery_complete=True,
                failed=0,
                gap_reasons=[],
                inaccessible=0,
                processing=0,
                ready=1,
                unsafe_to_parse=0,
                unknown_branches=0,
                unstable=0,
                unsupported=0,
            ),
            gap_reasons=(),
            run_id=RUN_ID,
            run_status="ready",
            workspace_id=WORKSPACE_ID,
        )
        self.history_reads = 0
        self.search_reads = 0

    def get_context(self, *, user_id: UUID, workspace_id: UUID) -> QueryContext | None:
        assert user_id == USER_ID
        return self.context if workspace_id == WORKSPACE_ID else None

    def get_by_idempotency(
        self, *, workspace_id: UUID, idempotency_key: str
    ) -> StoredQuestionResult | None:
        assert workspace_id == WORKSPACE_ID
        assert idempotency_key == "question-1"
        return None

    def list_results(
        self, *, user_id: UUID, workspace_id: UUID, limit: int
    ) -> list[StoredQuestionResult]:
        self.history_reads += 1
        raise AssertionError("standalone questions must not load conversation history")

    def list_ready_blocks(self, *, context: QueryContext) -> list[RetrievedBlock]:
        assert context == self.context
        return [self._block()]

    def search_blocks(self, **_kwargs: object) -> list[RetrievedBlock]:
        self.search_reads += 1
        return [self._block()]

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
            generation_status=generation_status,
            message=message,
            now=now,
            passages=passages,
            policy_version="retrieval-policy-v1",
            question=question,
            status="evidence_retrieved",
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
        assert idempotency_key == "question-1"
        return self._stored(
            claims=claims,
            context=context,
            generation_status="completed",
            message=message,
            now=now,
            passages=passages,
            policy_version=policy_version,
            question=question,
            status=status,
            coverage_gap_reasons=coverage_gap_reasons,
        )

    def _block(self) -> RetrievedBlock:
        return RetrievedBlock(
            block_id=BLOCK_ID,
            drive_file_id="drive-service-level",
            line_start_one_based=1,
            origin_kind="text_lines",
            page_index_zero_based=None,
            path=("Evidence", "service-level.txt"),
            printed_page_label=None,
            source_name="service-level.txt",
            source_file_id=SOURCE_ID,
            text="The current service level is Gold.",
        )

    def _stored(
        self,
        *,
        claims: tuple[ClaimRecord, ...],
        context: QueryContext,
        generation_status: str,
        message: str,
        now: datetime,
        passages: tuple[PassageRecord, ...],
        policy_version: str,
        question: str,
        status: str,
        coverage_gap_reasons: tuple[str, ...] | None = None,
    ) -> StoredQuestionResult:
        return StoredQuestionResult(
            answer_id=ANSWER_ID,
            claims=claims,
            coverage_gap_reasons=(
                context.gap_reasons if coverage_gap_reasons is None else coverage_gap_reasons
            ),
            created_at=now,
            generation_status=generation_status,
            message=message,
            passages=passages,
            policy_version=policy_version,
            question=question,
            question_id=QUESTION_ID,
            status=status,
        )


class _ComparisonStore(_QueryStore):
    def __init__(self) -> None:
        super().__init__()
        self.context = replace(
            self.context,
            coverage=self.context.coverage.model_copy(update={"discovered": 2, "ready": 2}),
        )
        self.blocks = [
            RetrievedBlock(
                block_id=UUID("50000000-0000-4000-8000-000000000011"),
                drive_file_id="drive-proposal",
                line_start_one_based=1,
                origin_kind="text_lines",
                page_index_zero_based=None,
                path=("Evidence", "proposal.txt"),
                printed_page_label=None,
                source_name="proposal.txt",
                source_file_id=UUID("40000000-0000-4000-8000-000000000011"),
                text="Proposal service level: Silver.",
            ),
            RetrievedBlock(
                block_id=UUID("50000000-0000-4000-8000-000000000012"),
                drive_file_id="drive-contract",
                line_start_one_based=1,
                origin_kind="text_lines",
                page_index_zero_based=None,
                path=("Evidence", "signed_contract.txt"),
                printed_page_label=None,
                source_name="signed_contract.txt",
                source_file_id=UUID("40000000-0000-4000-8000-000000000012"),
                text="Signed contract service level: Gold.",
            ),
        ]

    def list_ready_blocks(self, *, context: QueryContext) -> list[RetrievedBlock]:
        assert context == self.context
        return self.blocks

    def search_blocks(self, **_kwargs: object) -> list[RetrievedBlock]:
        self.search_reads += 1
        return self.blocks


class _RepairingComparisonProvider:
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
        by_source = {passage.source_name: passage for passage in passages}
        proposal = by_source["proposal.txt"]
        contract = by_source["signed_contract.txt"]
        if self.calls == 1:
            return AnswerDraft(
                claims=[
                    ClaimDraft(
                        claim_id=UUID("80000000-0000-4000-8000-000000000001"),
                        evidence=[
                            DraftEvidenceRef(
                                block_id=proposal.block_id,
                                exact_quote=proposal.exact_quote,
                                value="Silver",
                            )
                        ],
                        relation="fact",
                        text=proposal.exact_quote,
                        value="Silver",
                    )
                ],
                summary="The proposal states Silver.",
            )
        return AnswerDraft(
            claims=[
                ClaimDraft(
                    claim_id=UUID("80000000-0000-4000-8000-000000000002"),
                    evidence=[
                        DraftEvidenceRef(
                            block_id=proposal.block_id,
                            entity="service agreement",
                            exact_quote=proposal.exact_quote,
                            field="service level",
                            scope="service agreement",
                            value="Silver",
                        ),
                        DraftEvidenceRef(
                            block_id=contract.block_id,
                            entity="service agreement",
                            exact_quote=contract.exact_quote,
                            field="service level",
                            scope="service agreement",
                            value="Gold",
                        ),
                    ],
                    relation="conflict",
                    text=f"{proposal.exact_quote} {contract.exact_quote}",
                )
            ],
            summary="The proposal and signed contract state different service levels.",
        )


def _active_session() -> ActiveSessionRecord:
    return ActiveSessionRecord(
        account=AccountRecord(
            display_name="Ada Analyst",
            email="ada@example.test",
            refresh_token_ciphertext=b"server-only",
            refresh_token_key_version=1,
            scopes=("https://www.googleapis.com/auth/drive.readonly",),
            token_status="active",
            user_id=USER_ID,
        ),
        expires_at=NOW + timedelta(days=7),
    )


def test_unsupported_structured_clause_stops_before_sampled_retrieval() -> None:
    store = _QueryStore()
    service = QueryService(repository=store, rate_limiter=_RateLimiter(), clock=lambda: NOW)
    unsupported = StructuredAnalysisResult(
        audits=(),
        claims=(),
        examined_rows=3,
        malformed_rows=0,
        matched_rows=0,
        message="A requested structured clause could not be executed completely.",
        reconciliation=ReconciliationAudit(),
        status="unsupported",
        tables_examined=1,
    )

    with patch(
        "extent_api.services.query.analyze_structured_question",
        return_value=unsupported,
    ):
        result = service.ask(
            active_session=_active_session(),
            idempotency_key="question-1",
            question="What is the total amount across all records?",
            workspace_id=WORKSPACE_ID,
        )

    assert result.status == "insufficient"
    assert result.claims == []
    assert result.policy_version == "structured-analysis-policy-v1"
    assert store.search_reads == 0


def test_standalone_question_skips_conversation_history() -> None:
    store = _QueryStore()
    service = QueryService(repository=store, rate_limiter=_RateLimiter(), clock=lambda: NOW)

    result = service.ask(
        active_session=_active_session(),
        idempotency_key="question-1",
        question="What is the current service level?",
        workspace_id=WORKSPACE_ID,
    )

    assert result.status == "evidence_retrieved"
    assert store.history_reads == 0
    assert store.search_reads == 1


def test_multi_scope_question_repairs_one_sided_draft_and_preserves_conflict() -> None:
    store = _ComparisonStore()
    provider = _RepairingComparisonProvider()
    service = QueryService(
        answer_provider=provider,
        repository=store,
        rate_limiter=_RateLimiter(),
        clock=lambda: NOW,
    )

    result = service.ask(
        active_session=_active_session(),
        idempotency_key="question-1",
        question=("What service levels are stated for the proposal and the signed contract?"),
        workspace_id=WORKSPACE_ID,
    )

    assert provider.calls == 2
    assert result.status == "conflict"
    assert len(result.claims) == 1
    assert result.claims[0].relation == "conflict"
    assert {citation.source_name for citation in result.claims[0].citations} == {
        "proposal.txt",
        "signed_contract.txt",
    }
