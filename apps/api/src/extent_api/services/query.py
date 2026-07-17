"""Bounded retrieval orchestration for the first real workspace question flow."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

from extent_api.database.identity_repository import ActiveSessionRecord
from extent_api.database.query_repository import (
    ClaimRecord,
    PassageRecord,
    QueryContext,
    RetrievedBlock,
    StoredQuestionResult,
)
from extent_api.providers.chat_completion import (
    ModelConversationTurn,
    ModelGenerationError,
    ModelPassage,
)
from extent_api.providers.embeddings import (
    Embedding,
    EmbeddingGenerationError,
    EmbeddingProvider,
)
from extent_api.query_models import (
    CLARIFICATION_POLICY_VERSION,
    SOURCE_STATE_POLICY_VERSION,
    WorkspaceApprovedClaimView,
    WorkspaceEvidencePassageView,
    WorkspaceQuestionResultView,
)
from extent_api.rate_limiting import QueryRateLimiter
from extent_api.services.exhaustive_extraction import (
    EXHAUSTIVE_EXTRACTION_POLICY_VERSION,
    ExhaustiveExtractionResult,
    ExhaustiveRequest,
    ExhaustiveRequestNeedsClarification,
    extract_values,
    parse_exhaustive_request,
)
from extent_api.services.publication import (
    AnswerDraft,
    ApprovedCitation,
    ApprovedClaim,
    DraftEvidenceRef,
    EvidenceBlock,
    PdfBlockOrigin,
    PublicationContext,
    PublicationResult,
    RetrievedPassage,
    TextBlockOrigin,
    authorize_answer_draft,
    coverage_gaps,
)
from extent_api.services.query_planning import QueryPlan, plan_query
from extent_api.services.structured_analysis import (
    STRUCTURED_ANALYSIS_POLICY_VERSION,
    StructuredAnalysisResult,
    analyze_structured_question,
)
from extent_api.token_forms import is_likely_plural, tokens_equivalent

_TOKEN = re.compile(r"[^\W_]+|\d+", re.UNICODE)
_CURRENCY_AMOUNT = re.compile(
    r"(?P<currency>[$€£]|USD|CAD|EUR|GBP)\s*"
    r"(?P<amount>\d+(?:,\d{3})*(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
_SUFFIXED_CURRENCY_AMOUNT = re.compile(
    r"(?P<amount>\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*"
    r"(?P<currency>USD|CAD|EUR|GBP)\b",
    re.IGNORECASE,
)
_PERCENT_VALUE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_FORMATTED_NUMBER = re.compile(r"\b(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)\b")
_PLAIN_NUMBER = re.compile(r"\b\d+\b")
_ISO_DATE_VALUE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONTH_DATE_VALUE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4}\b",
    re.IGNORECASE,
)
_EMAIL_VALUE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_URL_VALUE = re.compile(r"\bhttps?://[^\s<>]+", re.I)
_IDENTIFIER_VALUE = re.compile(
    r"\b(?=[A-Z0-9_/-]*[A-Z])(?=[A-Z0-9_/-]*\d)"
    r"[A-Z][A-Z0-9]*(?:[-_/][A-Z0-9]+)+\b",
    re.I,
)
_EXPLICIT_VALUE_STATUS = re.compile(
    r"\b(?:included|none|not\s+(?:applicable|available|included|provided|quoted|"
    r"received)|pending|tbd|unknown|unlimited|waived)\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "about",
    "all",
    "and",
    "are",
    "does",
    "for",
    "from",
    "have",
    "how",
    "into",
    "is",
    "me",
    "our",
    "please",
    "show",
    "that",
    "the",
    "this",
    "tell",
    "was",
    "what",
    "what's",
    "whats",
    "when",
    "where",
    "which",
    "with",
}
_SINGLE_TOTAL_TERMS = {"aggregate", "combined", "final", "overall", "package", "total"}
_TERMINAL_RUNS = {"ready", "partial"}
_EXPLICIT_COMPLETE_SCOPE = re.compile(
    r"\b(?:all|each|every|dataset|file|record|row|source|table)s?\b|"
    r"\b(?:break\s*down|group(?:ed)?|per)\b|\bby\b",
    re.IGNORECASE,
)
_SOURCE_STATE_QUESTION = re.compile(
    r"\b(?:folder|files?|sources?)\b.{0,100}\b(?:available|complete|expected|found|"
    r"incomplete|missing|ready|sync(?:ed|hronized)?)\b|"
    r"\b(?:available|complete|expected|found|incomplete|missing|ready)\b.{0,100}"
    r"\b(?:folder|files?|sources?)\b",
    re.IGNORECASE,
)
_RETRIEVAL_CANDIDATE_LIMIT = 32
_PASSAGE_LIMIT = 6
_PASSAGE_PER_SOURCE_LIMIT = 3
_PASSAGE_EXCERPT_LIMIT = 280
_CLARIFICATION_MESSAGE = "Which prior value or subject do you mean?"
_EXPLICIT_MULTI_FACT_QUESTION = re.compile(
    r"\b(?:break\s*down|compare|comparison|differences?|list|summari[sz]e|"
    r"what\s+are|which\s+are)\b",
    re.IGNORECASE,
)
_STRUCTURED_VALUE_QUESTION = re.compile(
    r"^\s*(?:(?:what(?:'s|s|\s+(?:is|are|was|were))|"
    r"what\b.{1,60}\b(?:is|are|was|were)\s+"
    r"(?:listed|shown|recorded|provided)|"
    r"which\s+(?:is|are|was|were)|who\b|"
    r"where\s+(?:is|are|was|were)|"
    r"when(?:\s+(?:is|are|was|were))?|how\s+(?:much|many)|"
    r"(?:show|give|tell)\s+(?:me\s+)?)\b)",
    re.IGNORECASE,
)
_FIELD_SCOPE_PREPOSITION = re.compile(r"\b(?:at|for|from|in|of|on)\b", re.IGNORECASE)
_WHO_VERBAL_QUESTION = re.compile(
    r"^\s*who\s+(?:(?:can|could|did|does|may|might|must|should|will|would)\s+)?"
    r"(?P<verb>[^\W\d_]+)\b",
    re.IGNORECASE,
)
_STRONG_ASSIGNMENT_SEPARATOR = re.compile(r":|=|\s[-\u2013\u2014]\s")
_FOLLOW_UP_REFERENCE = re.compile(
    r"\b(?:former|it|latter|one|ones|same|that|them|these|they|this|those)\b",
    re.IGNORECASE,
)
_FOLLOW_UP_GENERIC_TERMS = {
    "change",
    "changed",
    "compare",
    "comparison",
    "did",
    "difference",
    "different",
    "does",
    "former",
    "it",
    "latter",
    "one",
    "ones",
    "same",
    "that",
    "them",
    "these",
    "they",
    "this",
    "those",
}
_CONTROLLED_EVIDENCE = re.compile(
    r"\b(?:approved|authorized|change[- ]control(?:led)?|executed|ratified|signed)\b",
    re.IGNORECASE,
)
_CONTROL_IDENTIFIER = re.compile(
    r"\b(?:approval|change|revision|signature|version)\s*(?:id|number|no\.?|:)\b",
    re.IGNORECASE,
)
_LOW_AUTHORITY_EVIDENCE = re.compile(
    r"\b(?:anecdotal|draft|estimate|informal|narrative|note|proposed|rumor|"
    r"unapproved|uncontrolled|unsupported|unverified)\b",
    re.IGNORECASE,
)
_NEGATED_CONTROL_EVIDENCE = re.compile(
    r"\b(?:lacks?|no|not|pending|until|without)\b.{0,60}\b(?:approv(?:al|ed)|"
    r"authoriz(?:ation|ed)|change[- ]?(?:control|request)|executed|appointment\s+letter|"
    r"meeting\s+resolution|ratif(?:ied|ication)|signed)\b",
    re.IGNORECASE,
)


class WorkspaceNotFound(RuntimeError):
    pass


class WorkspaceNotReady(RuntimeError):
    pass


class RetrievalUnavailable(RuntimeError):
    pass


class QueryStore(Protocol):
    def get_context(self, *, user_id: UUID, workspace_id: UUID) -> QueryContext | None: ...

    def get_by_idempotency(
        self, *, workspace_id: UUID, idempotency_key: str
    ) -> StoredQuestionResult | None: ...

    def list_results(
        self, *, user_id: UUID, workspace_id: UUID, limit: int
    ) -> list[StoredQuestionResult]: ...

    def list_ready_blocks(self, *, context: QueryContext) -> list[RetrievedBlock]: ...

    def search_blocks(
        self,
        *,
        context: QueryContext,
        embedding: Embedding | None,
        limit: int,
        prefer_value_evidence: bool,
        structured_token_sequences: tuple[tuple[str, ...], ...],
        tokens: tuple[str, ...],
    ) -> list[RetrievedBlock]: ...

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
    ) -> StoredQuestionResult: ...

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
    ) -> StoredQuestionResult: ...


class AnswerProvider(Protocol):
    def generate(
        self,
        *,
        history: list[ModelConversationTurn],
        passages: list[ModelPassage],
        question: str,
    ) -> AnswerDraft: ...


class QueryService:
    def __init__(
        self,
        *,
        answer_provider: AnswerProvider | None = None,
        clock: Callable[[], datetime] | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        rate_limiter: QueryRateLimiter,
        repository: QueryStore,
    ) -> None:
        self._repository = repository
        self._answer_provider = answer_provider
        self._embedding_provider = embedding_provider
        self._rate_limiter = rate_limiter
        self._clock = clock or (lambda: datetime.now(UTC))

    def ask(
        self,
        *,
        active_session: ActiveSessionRecord,
        idempotency_key: str,
        question: str,
        workspace_id: UUID,
    ) -> WorkspaceQuestionResultView:
        context = self._repository.get_context(
            user_id=active_session.account.user_id, workspace_id=workspace_id
        )
        if context is None:
            raise WorkspaceNotFound
        existing = self._repository.get_by_idempotency(
            workspace_id=workspace_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            if existing.question != question.strip():
                raise ValueError("idempotency key was used for another question")
            return project_question_result(existing)
        if context.run_status not in _TERMINAL_RUNS:
            raise WorkspaceNotReady

        now = self._clock()
        self._rate_limiter.consume(user_id=active_session.account.user_id, now=now)
        normalized_question = question.strip()
        if _SOURCE_STATE_QUESTION.search(normalized_question):
            stored = self._repository.store_publication_result(
                claims=(),
                context=context,
                idempotency_key=idempotency_key,
                message=_source_state_message(context),
                now=now,
                passages=(),
                policy_version=SOURCE_STATE_POLICY_VERSION,
                question=normalized_question,
                status="insufficient",
            )
            return project_question_result(stored)
        query_plan = plan_query(normalized_question)
        exhaustive_request = parse_exhaustive_request(normalized_question)
        complete_blocks: list[RetrievedBlock] | None = None
        if isinstance(
            exhaustive_request, ExhaustiveRequestNeedsClarification
        ) and query_plan.mode not in {"mixed", "structured"}:
            stored = self._repository.store_publication_result(
                claims=(),
                context=context,
                idempotency_key=idempotency_key,
                message=exhaustive_request.message,
                now=now,
                passages=(),
                policy_version=CLARIFICATION_POLICY_VERSION,
                question=normalized_question,
                status="insufficient",
            )
            return project_question_result(stored)
        if query_plan.requires_complete_data:
            ready_blocks = self._repository.list_ready_blocks(context=context)
            complete_blocks = ready_blocks
            analysis = analyze_structured_question(
                ready_blocks,
                idempotency_key=idempotency_key,
                plan=query_plan,
                question=normalized_question,
                run_id=context.run_id,
            )
            if analysis.status in {"complete", "incomplete"} and (
                query_plan.mode != "mixed" or "join" in query_plan.intents
            ):
                return self._store_structured_analysis(
                    analysis,
                    context=context,
                    idempotency_key=idempotency_key,
                    now=now,
                    plan=query_plan,
                    question=normalized_question,
                )
            if isinstance(exhaustive_request, ExhaustiveRequest):
                return self._extract_values(
                    blocks=ready_blocks,
                    context=context,
                    idempotency_key=idempotency_key,
                    now=now,
                    question=normalized_question,
                    request=exhaustive_request,
                )
            if (
                query_plan.mode == "structured" or "join" in query_plan.intents
            ) and not _can_fallback_from_structured(normalized_question, plan=query_plan):
                return self._store_structured_analysis(
                    analysis,
                    context=context,
                    idempotency_key=idempotency_key,
                    now=now,
                    plan=query_plan,
                    question=normalized_question,
                )
        if isinstance(exhaustive_request, ExhaustiveRequestNeedsClarification):
            stored = self._repository.store_publication_result(
                claims=(),
                context=context,
                idempotency_key=idempotency_key,
                message=exhaustive_request.message,
                now=now,
                passages=(),
                policy_version=CLARIFICATION_POLICY_VERSION,
                question=normalized_question,
                status="insufficient",
            )
            return project_question_result(stored)
        if isinstance(exhaustive_request, ExhaustiveRequest):
            return self._extract_values(
                context=context,
                idempotency_key=idempotency_key,
                now=now,
                question=normalized_question,
                request=exhaustive_request,
            )
        history = self._repository.list_results(
            user_id=active_session.account.user_id,
            workspace_id=workspace_id,
            limit=2,
        )
        model_history = _model_history(history)
        is_follow_up = _needs_bounded_context(normalized_question)
        if is_follow_up and not any(turn.claim_summaries for turn in model_history):
            stored = self._repository.store_publication_result(
                claims=(),
                context=context,
                idempotency_key=idempotency_key,
                message=_CLARIFICATION_MESSAGE,
                now=now,
                passages=(),
                policy_version=CLARIFICATION_POLICY_VERSION,
                question=normalized_question,
                status="insufficient",
            )
            return project_question_result(stored)

        retrieval_question = _retrieval_question(
            normalized_question, history=model_history, is_follow_up=is_follow_up
        )
        tokens = _query_tokens(retrieval_question)
        assignment_token_sequences = _query_assignment_token_sequences(
            retrieval_question, tokens=tokens
        )
        prefer_value_evidence = _question_prefers_structured_value(normalized_question) or (
            is_follow_up
            and any(
                _question_prefers_structured_value(turn.question)
                for turn in reversed(model_history)
            )
        )
        embedding: Embedding | None = None
        if self._embedding_provider is not None:
            try:
                embedding = self._embedding_provider.embed([retrieval_question])[0]
            except EmbeddingGenerationError as error:
                raise RetrievalUnavailable from error
        if complete_blocks is not None and query_plan.mode == "mixed":
            candidates = complete_blocks
        elif prefer_value_evidence and embedding is not None:
            lexical_candidates = self._repository.search_blocks(
                context=context,
                embedding=None,
                limit=_RETRIEVAL_CANDIDATE_LIMIT,
                prefer_value_evidence=True,
                structured_token_sequences=assignment_token_sequences,
                tokens=tokens,
            )
            semantic_candidates = self._repository.search_blocks(
                context=context,
                embedding=embedding,
                limit=_RETRIEVAL_CANDIDATE_LIMIT,
                prefer_value_evidence=True,
                structured_token_sequences=assignment_token_sequences,
                tokens=tokens,
            )
            candidates = _merge_retrieved_blocks(lexical_candidates, semantic_candidates)
        else:
            candidates = self._repository.search_blocks(
                context=context,
                embedding=embedding,
                limit=_RETRIEVAL_CANDIDATE_LIMIT,
                prefer_value_evidence=prefer_value_evidence,
                structured_token_sequences=assignment_token_sequences,
                tokens=tokens,
            )
            if not candidates and tokens:
                # Old or differently configured vectors are deliberately excluded.
                # Lexical evidence remains usable until the source is reindexed.
                candidates = self._repository.search_blocks(
                    context=context,
                    embedding=None,
                    limit=_RETRIEVAL_CANDIDATE_LIMIT,
                    prefer_value_evidence=prefer_value_evidence,
                    structured_token_sequences=assignment_token_sequences,
                    tokens=tokens,
                )
        passages = _select_passages(
            candidates,
            assignment_token_sequences=assignment_token_sequences,
            prefer_value_evidence=prefer_value_evidence,
            require_token_match=embedding is None,
            tokens=tokens,
        )
        if complete_blocks is not None and query_plan.mode == "mixed":
            relevant_block_count = sum(
                _token_coverage(candidate.text, tokens=tokens) > 0
                for candidate in complete_blocks
            )
            if relevant_block_count > _PASSAGE_LIMIT:
                stored = self._repository.store_retrieval_result(
                    context=context,
                    idempotency_key=idempotency_key,
                    message=(
                        f"Mixed-source synthesis found {relevant_block_count} relevant "
                        f"blocks, exceeding the {_PASSAGE_LIMIT}-passage verified answer "
                        "boundary; narrow the comparison scope."
                    ),
                    now=now,
                    passages=passages,
                    question=normalized_question,
                )
                return project_question_result(stored)
        if query_plan.mode == "direct" and any(
            candidate.pipeline_version
            in {"csv-record-v1", "csv-record-v2", "docx-body-v1", "docx-body-v2"}
            for candidate in candidates
        ):
            analysis = analyze_structured_question(
                self._repository.list_ready_blocks(context=context),
                idempotency_key=idempotency_key,
                plan=query_plan,
                question=normalized_question,
                run_id=context.run_id,
            )
            if (
                analysis.applicable
                and analysis.claims
                and (
                    analysis.examined_rows == 1
                    or analysis.matched_rows < analysis.examined_rows
                )
            ):
                return self._store_structured_analysis(
                    analysis,
                    context=context,
                    idempotency_key=idempotency_key,
                    now=now,
                    plan=query_plan,
                    question=normalized_question,
                )
        if not passages:
            stored = self._repository.store_retrieval_result(
                context=context,
                idempotency_key=idempotency_key,
                message=_no_evidence_message(context),
                now=now,
                passages=passages,
                question=normalized_question,
            )
            return project_question_result(stored)
        if self._answer_provider is None:
            stored = self._repository.store_retrieval_result(
                context=context,
                idempotency_key=idempotency_key,
                message=(
                    "Relevant source passages were retrieved. "
                    "Answer generation is not configured yet."
                ),
                now=now,
                passages=passages,
                question=normalized_question,
            )
            return project_question_result(stored)

        evidence_blocks = _evidence_blocks(candidates, passages=passages, context=context)
        try:
            draft = self._answer_provider.generate(
                history=model_history,
                passages=_model_passages(passages),
                question=normalized_question,
            )
        except ModelGenerationError as first_error:
            try:
                draft = self._answer_provider.generate(
                    history=[],
                    passages=_model_passages(_recovery_passages(passages)),
                    question=normalized_question,
                )
            except ModelGenerationError as retry_error:
                recovered = _deterministic_answer_recovery(
                    candidates,
                    idempotency_key=idempotency_key,
                    question=normalized_question,
                    run_id=context.run_id,
                )
                if recovered:
                    stored = self._repository.store_publication_result(
                        claims=recovered,
                        context=context,
                        idempotency_key=idempotency_key,
                        message=(
                            "The answer model failed twice; Extent recovered the answer "
                            "deterministically from explicit source fields."
                        ),
                        now=now,
                        passages=(),
                        question=normalized_question,
                        status="evidence_supported",
                    )
                    return project_question_result(stored)
                stored = self._repository.store_retrieval_result(
                    context=context,
                    generation_status="failed",
                    idempotency_key=idempotency_key,
                    message=(
                        f"{_generation_failure_summary(first_error, retry_error)} "
                        "Retrieved evidence is shown for review."
                    ),
                    now=now,
                    passages=passages,
                    question=normalized_question,
                )
                return project_question_result(stored)

        if not draft.claims and draft.needs_clarification is None:
            # A valid empty response can be a transient model miss. Retry once
            # without conversation history before deterministic recovery.
            try:
                retry_draft = self._answer_provider.generate(
                    history=[],
                    passages=_model_passages(passages),
                    question=normalized_question,
                )
            except ModelGenerationError:
                retry_draft = draft
            if retry_draft.claims or retry_draft.needs_clarification is not None:
                draft = retry_draft

        authority_guard_failed = False
        if _has_one_sided_authority_tension(draft, blocks=evidence_blocks):
            try:
                authority_draft = self._answer_provider.generate(
                    history=[],
                    passages=_model_passages(passages),
                    question=_authority_recovery_question(normalized_question),
                )
            except ModelGenerationError:
                authority_draft = draft
            if _is_authority_improvement(
                authority_draft, previous=draft, blocks=evidence_blocks
            ):
                draft = authority_draft
            else:
                authority_guard_failed = True
                draft = AnswerDraft(
                    claims=[],
                    summary=(
                        "A one-sided lower-authority answer was withheld because "
                        "controlled evidence was also present."
                    ),
                )

        if draft.needs_clarification is not None:
            stored = self._repository.store_publication_result(
                claims=(),
                context=context,
                idempotency_key=idempotency_key,
                message=_CLARIFICATION_MESSAGE,
                now=now,
                passages=passages,
                policy_version=CLARIFICATION_POLICY_VERSION,
                question=normalized_question,
                status="insufficient",
            )
            return project_question_result(stored)

        if not draft.claims and not authority_guard_failed:
            recovered = _deterministic_answer_recovery(
                candidates,
                idempotency_key=idempotency_key,
                question=normalized_question,
                run_id=context.run_id,
            )
            if recovered:
                stored = self._repository.store_publication_result(
                    claims=recovered,
                    context=context,
                    idempotency_key=idempotency_key,
                    message=(
                        "The retrieved evidence contained an explicit answer, which was "
                        "rendered deterministically after model abstention."
                    ),
                    now=now,
                    passages=(),
                    question=normalized_question,
                    status="evidence_supported",
                )
                return project_question_result(stored)

        publication = authorize_answer_draft(
            draft,
            blocks=evidence_blocks,
            context=PublicationContext(
                coverage=context.coverage,
                included_block_ids=[block.block_id for block in evidence_blocks],
                ingestion_run_id=context.run_id,
                run_terminal=context.run_status in _TERMINAL_RUNS,
                workspace_id=context.workspace_id,
            ),
        )
        publication = _resolve_conflict_authority(
            publication,
            blocks=evidence_blocks,
            draft=draft,
        )
        scope_required = _requires_value_scope(
            normalized_question,
            evidence_texts=tuple(candidate.text for candidate in candidates),
            publication=publication,
        )
        publication = _focus_publication(
            publication,
            evidence_texts=tuple(candidate.text for candidate in candidates),
            question=normalized_question,
            scope_required=scope_required,
        )
        stored = self._repository.store_publication_result(
            claims=_claim_records(publication, candidates),
            context=context,
            coverage_gap_reasons=tuple(publication.coverage_gap_reasons),
            idempotency_key=idempotency_key,
            message=_publication_message(publication, scope_required=scope_required),
            now=now,
            passages=_publication_passages(
                publication, candidates=candidates, retrieved=passages
            ),
            question=normalized_question,
            status=publication.status,
        )
        return project_question_result(stored)

    def _extract_values(
        self,
        *,
        blocks: list[RetrievedBlock] | None = None,
        context: QueryContext,
        idempotency_key: str,
        now: datetime,
        question: str,
        request: ExhaustiveRequest,
    ) -> WorkspaceQuestionResultView:
        extraction = extract_values(
            self._repository.list_ready_blocks(context=context) if blocks is None else blocks,
            idempotency_key=idempotency_key,
            request=request,
            run_id=context.run_id,
        )
        gaps = tuple(coverage_gaps(context.coverage))
        status = (
            "coverage_limited"
            if gaps or extraction.ambiguous_count or extraction.overflowed
            else "evidence_supported"
            if extraction.claims
            else "insufficient"
        )
        stored = self._repository.store_publication_result(
            claims=extraction.claims,
            context=context,
            coverage_gap_reasons=gaps,
            idempotency_key=idempotency_key,
            message=_exhaustive_extraction_message(
                extraction,
                has_coverage_gaps=bool(gaps),
                ready_files=context.coverage.ready,
                request=request,
            ),
            now=now,
            passages=(),
            policy_version=EXHAUSTIVE_EXTRACTION_POLICY_VERSION,
            question=question,
            status=status,
        )
        return project_question_result(stored)

    def _store_structured_analysis(
        self,
        analysis: StructuredAnalysisResult,
        *,
        context: QueryContext,
        idempotency_key: str,
        now: datetime,
        plan: QueryPlan,
        question: str,
    ) -> WorkspaceQuestionResultView:
        gaps = tuple(coverage_gaps(context.coverage))
        # A deterministic result that excluded malformed or untraceable rows is
        # not safe to publish as an exact complete-data claim.
        claims = analysis.claims if analysis.complete else ()
        message = analysis.message
        if analysis.status == "incomplete":
            attempted_rows = analysis.examined_rows + analysis.malformed_rows
            message = (
                "Complete analysis could not be published: "
                f"{analysis.malformed_rows} of {attempted_rows} row(s) were malformed "
                "or lacked exact citation lineage. Correct or re-ingest the affected "
                "source, then retry."
            )
        if gaps:
            if "completeness" in plan.intents:
                claims = ()
            message = _incomplete_analysis_message(context, fallback=analysis.message)
        status = (
            "coverage_limited"
            if gaps or not analysis.complete
            else "evidence_supported"
            if claims
            else "insufficient"
        )
        stored = self._repository.store_publication_result(
            claims=claims,
            context=context,
            coverage_gap_reasons=gaps,
            idempotency_key=idempotency_key,
            message=message,
            now=now,
            passages=(),
            policy_version=STRUCTURED_ANALYSIS_POLICY_VERSION,
            question=question,
            status=status,
        )
        return project_question_result(stored)


def _exhaustive_extraction_message(
    extraction: ExhaustiveExtractionResult,
    *,
    has_coverage_gaps: bool,
    ready_files: int,
    request: ExhaustiveRequest,
) -> str:
    file_label = "file" if ready_files == 1 else "files"
    target = request.display_target
    if extraction.overflowed:
        return (
            "More than 200 matching entries were found while scanning readable files "
            f"for explicit “{target}” label/value structures. No truncated list was "
            "published; ask for a more specific field label."
        )
    ready_count = str(ready_files) if ready_files <= 999_999 else "many"
    scan = (
        f"Scanned all blocks in {'all ' if not has_coverage_gaps else ''}{ready_count} "
        f"readable {file_label} for explicit “{target}” label/value structures"
    )
    finding = (
        f"; found {extraction.unique_count} distinct extracted "
        f"{'entry' if extraction.unique_count == 1 else 'entries'}."
        if extraction.unique_count
        else "; found no supported matches."
    )
    if has_coverage_gaps or extraction.ambiguous_count:
        reasons: list[str] = []
        if has_coverage_gaps:
            reasons.append("some files were unavailable")
        if extraction.ambiguous_count:
            ambiguous_count = (
                str(extraction.ambiguous_count)
                if extraction.ambiguous_count <= 999_999
                else "Many"
            )
            reasons.append(
                f"{ambiguous_count} "
                f"{'passage was' if extraction.ambiguous_count == 1 else 'passages were'} "
                "structurally ambiguous"
            )
        return (
            f"{scan}{finding} {' and '.join(reasons).capitalize()}, so this extraction "
            "is partial."
        )
    return f"{scan}{finding}"


def _incomplete_analysis_message(context: QueryContext, *, fallback: str) -> str:
    """Explain incomplete execution exclusively from trusted ingestion state."""

    details = _source_issue_details(context)
    if not details:
        details = [reason.replace("_", " ") for reason in coverage_gaps(context.coverage)]
    reason = ", ".join(details) or "incomplete ingestion coverage"
    prefix = (
        f"Complete analysis is unavailable because the actual source state reports {reason}."
    )
    if len(prefix) >= 280:
        return prefix[:277].rstrip() + "..."
    remaining = 280 - len(prefix) - 1
    suffix = " ".join(fallback.split())
    return f"{prefix} {suffix[:remaining].rstrip()}" if suffix and remaining > 0 else prefix


def _generation_failure_summary(
    first: ModelGenerationError, retry: ModelGenerationError
) -> str:
    labels = {
        "provider_unavailable": "the answer provider was unavailable",
        "invalid_response": "the answer provider returned an invalid response",
    }
    first_label = labels[first.code]
    retry_label = labels[retry.code]
    if first.code == retry.code:
        return (
            f"Answer generation failed because {first_label} on the initial request "
            "and the single reduced-context recovery attempt."
        )
    return (
        f"Answer generation failed because {first_label} initially and {retry_label} "
        "on the single reduced-context recovery attempt."
    )


def _no_evidence_message(context: QueryContext) -> str:
    """Distinguish an evidence miss from actual source unavailability."""

    unavailable = _source_issue_details(context)
    if not unavailable:
        unavailable = [reason.replace("_", " ") for reason in coverage_gaps(context.coverage)]
    if unavailable:
        return (
            "No supporting evidence was found in readable sources; source availability "
            f"is incomplete ({', '.join(unavailable)})."
        )[:280]
    return "No supporting evidence was found in the complete readable source set."


def _source_issue_details(context: QueryContext) -> list[str]:
    labels = {
        "access_denied": "access denied",
        "missing_file": "missing file",
        "partial_sync": "partial synchronization",
        "source_failed": "source failed",
        "unsafe_to_parse": "unparseable source",
        "capped": "capped source",
        "unsupported": "unsupported source",
    }
    details: list[str] = []
    for kind, issues in sorted(
        (
            (kind, [issue for issue in context.source_issues if issue.kind == kind])
            for kind in {issue.kind for issue in context.source_issues}
        ),
        key=lambda item: item[0],
    ):
        label = labels.get(kind)
        if label is None:
            continue
        names = [issue.source_name for issue in issues if issue.source_name]
        if names:
            rendered_names = ", ".join(f"“{name}”" for name in names[:2])
            details.append(f"{label}: {rendered_names}")
        elif kind == "partial_sync":
            details.append(label)
        else:
            details.append(f"{len(issues)} {label} source(s)")
    return details


def _model_history(results: Sequence[StoredQuestionResult]) -> list[ModelConversationTurn]:
    return [
        ModelConversationTurn(
            claim_summaries=[claim.text for claim in result.claims[:3]],
            question=result.question,
        )
        for result in results[-2:]
    ]


def _recovery_passages(passages: tuple[PassageRecord, ...]) -> tuple[PassageRecord, ...]:
    """Reduce a failed model request to the strongest compact evidence context."""

    value_bearing = tuple(
        passage
        for passage in passages
        if _contains_assignment_value(passage.exact_quote)
        or _STRONG_ASSIGNMENT_SEPARATOR.search(passage.exact_quote) is not None
    )
    return (value_bearing or passages)[:3]


def _can_fallback_from_structured(question: str, *, plan: QueryPlan) -> bool:
    """Allow scalar narrative facts to survive an unavailable table executor.

    Set-wide claims still fail closed: only a lone aggregate such as "how many
    locations are certified?" may continue through evidence retrieval.
    """

    return (
        set(plan.intents) == {"aggregate"} and _EXPLICIT_COMPLETE_SCOPE.search(question) is None
    )


def _source_state_message(context: QueryContext) -> str:
    """Report connector truth without accepting counts supplied in the question."""

    coverage = context.coverage
    issues = _source_issue_details(context)
    gaps = issues or [reason.replace("_", " ") for reason in coverage_gaps(coverage)]
    discovery = "complete" if coverage.discovery_complete else "still in progress"
    message = (
        f"Actual ingestion state: discovery is {discovery}; {coverage.discovered} file(s) "
        f"were discovered and {coverage.ready} are ready."
    )
    if gaps:
        message += f" Reported source issues: {', '.join(gaps)}."
    elif coverage.discovery_complete and coverage.ready == coverage.discovered:
        message += " The connector state does not support an incomplete-folder assertion."
    return message[:280]


def _deterministic_answer_recovery(
    blocks: list[RetrievedBlock],
    *,
    idempotency_key: str,
    question: str,
    run_id: UUID,
) -> tuple[ClaimRecord, ...]:
    """Recover unambiguous explicit fields without inventing model output."""

    tokens = _query_tokens(question)
    sequences = _query_assignment_token_sequences(question, tokens=tokens)
    if not sequences:
        return ()
    target_tokens = max(sequences, key=len)
    if not target_tokens:
        return ()
    request = ExhaustiveRequest(
        display_target=" ".join(target_tokens),
        normalized_target=" ".join(target_tokens),
        target_tokens=target_tokens,
    )
    extraction = extract_values(
        blocks,
        idempotency_key=f"{idempotency_key}:recovery",
        request=request,
        run_id=run_id,
    )
    if (
        extraction.ambiguous_count
        or extraction.overflowed
        or not extraction.claims
        or len(extraction.claims) > 3
        or (len(extraction.claims) > 1 and not _question_requests_multiple_facts(question))
    ):
        return ()
    if any(
        claim.value is None or _EXPLICIT_VALUE_STATUS.fullmatch(claim.value.strip())
        for claim in extraction.claims
    ):
        return ()
    return extraction.claims


def _retrieval_question(
    question: str, *, history: Sequence[ModelConversationTurn], is_follow_up: bool
) -> str:
    if not is_follow_up or not history:
        return question
    latest_with_claims = next(
        (turn for turn in reversed(history) if turn.claim_summaries), history[-1]
    )
    return " ".join(
        (question, latest_with_claims.question, *latest_with_claims.claim_summaries)
    )


def _needs_bounded_context(question: str) -> bool:
    if _FOLLOW_UP_REFERENCE.search(question) is None:
        return False
    return not (set(_query_tokens(question)) - _FOLLOW_UP_GENERIC_TERMS)


def _focus_publication(
    publication: PublicationResult,
    *,
    evidence_texts: Sequence[str],
    question: str,
    scope_required: bool | None = None,
) -> PublicationResult:
    requires_scope = (
        _requires_value_scope(question, evidence_texts=evidence_texts, publication=publication)
        if scope_required is None
        else scope_required
    )
    if requires_scope:
        return publication.model_copy(
            update={"claims": [], "retrieved_passages": [], "status": "insufficient"}
        )
    if (
        len(publication.claims) <= 1
        or any(claim.relation != "fact" for claim in publication.claims)
        or _question_requests_multiple_facts(question)
    ):
        return publication
    return publication.model_copy(update={"claims": publication.claims[:1]})


def _resolve_conflict_authority(
    publication: PublicationResult,
    *,
    blocks: Sequence[EvidenceBlock],
    draft: AnswerDraft,
) -> PublicationResult:
    """Prefer explicit controlled evidence without filename or recency heuristics."""

    blocks_by_id = {block.block_id: block for block in blocks}
    drafts_by_id = {claim.claim_id: claim for claim in draft.claims}
    resolved_claims: list[ApprovedClaim] = []
    for claim in publication.claims:
        if claim.relation != "conflict":
            resolved_claims.append(claim)
            continue
        proposed = drafts_by_id.get(claim.claim_id)
        if proposed is None or len(proposed.evidence) != 2:
            resolved_claims.append(claim.model_copy(update={"relation": "unclear"}))
            continue
        scored: list[tuple[int, int]] = []
        for index, reference in enumerate(proposed.evidence):
            block = blocks_by_id.get(reference.block_id)
            if block is None:
                continue
            score = _reference_authority_score(reference, block=block)
            if score is not None:
                scored.append((score, index))
        scored.sort(reverse=True)
        if len(scored) != 2 or scored[0][0] < 3 or scored[0][0] - scored[1][0] < 3:
            resolved_claims.append(claim.model_copy(update={"relation": "unclear"}))
            continue
        winner_index = scored[0][1]
        loser_index = 1 - winner_index
        winner = proposed.evidence[winner_index]
        loser = proposed.evidence[loser_index]
        if winner.value is None or loser.value is None:
            resolved_claims.append(claim.model_copy(update={"relation": "unclear"}))
            continue
        field = winner.field or "the disputed field"
        text = (
            f"Controlled evidence establishes {field} as {winner.value}; "
            f"lower-authority conflicting evidence states {loser.value}."
        )
        citations = [
            citation.model_copy(update={"role": "support"})
            for citation in claim.citations
            if citation.block_id == winner.block_id
        ]
        citations.extend(
            citation.model_copy(update={"role": "right"})
            for citation in claim.citations
            if citation.block_id == loser.block_id
        )
        resolved_claims.append(
            claim.model_copy(
                update={
                    "citations": citations,
                    "relation": "fact",
                    "text": text,
                    "value": winner.value,
                }
            )
        )
    status = publication.status
    if resolved_claims:
        relations = {claim.relation for claim in resolved_claims}
        if "conflict" in relations or any(
            claim.proposed_relation == "conflict" and claim.relation == "unclear"
            for claim in resolved_claims
        ):
            status = "conflict"
        elif "change" in relations:
            status = "changed"
        else:
            status = "evidence_supported"
    return publication.model_copy(update={"claims": resolved_claims, "status": status})


def _has_one_sided_authority_tension(
    draft: AnswerDraft, *, blocks: Sequence[EvidenceBlock]
) -> bool:
    if not draft.claims:
        return False
    blocks_by_id = {block.block_id: block for block in blocks}
    cited_scores: list[int] = []
    for claim in draft.claims:
        if claim.relation != "fact" or len(claim.evidence) != 1:
            return False
        reference = claim.evidence[0]
        block = blocks_by_id.get(reference.block_id)
        if block is None:
            return False
        score = _reference_authority_score(reference, block=block)
        if score is None:
            return False
        cited_scores.append(score)
    available_score = max(
        (_authority_text_score(block.normalized_text) for block in blocks),
        default=0,
    )
    return max(cited_scores, default=0) <= 0 and available_score >= 3


def _is_authority_improvement(
    candidate: AnswerDraft,
    *,
    previous: AnswerDraft,
    blocks: Sequence[EvidenceBlock],
) -> bool:
    if not candidate.claims:
        return False
    if any(
        claim.relation == "conflict" and len(claim.evidence) == 2 for claim in candidate.claims
    ):
        return True
    blocks_by_id = {block.block_id: block for block in blocks}

    def best_score(draft: AnswerDraft) -> int:
        scores = [
            score
            for claim in draft.claims
            for reference in claim.evidence
            if (block := blocks_by_id.get(reference.block_id)) is not None
            if (score := _reference_authority_score(reference, block=block)) is not None
        ]
        return max(scores, default=-100)

    return best_score(candidate) > best_score(previous)


def _authority_recovery_question(question: str) -> str:
    return (
        f"{question}\n\nAuthority-resolution instruction: compare the premise against all "
        "supplied evidence. If lower-authority evidence conflicts with controlled or "
        "approved evidence, return one atomic conflict claim per requested current "
        "field with both evidence branches. Do not repeat only the premise."
    )


def _reference_authority_score(
    reference: DraftEvidenceRef, *, block: EvidenceBlock
) -> int | None:
    quote_start = block.normalized_text.find(reference.exact_quote)
    if quote_start < 0:
        return None
    context_start = max(0, quote_start - 240)
    context_end = min(
        len(block.normalized_text), quote_start + len(reference.exact_quote) + 240
    )
    return _authority_text_score(block.normalized_text[context_start:context_end])


def _authority_text_score(text: str) -> int:
    score = 0
    negated = tuple(_NEGATED_CONTROL_EVIDENCE.finditer(text))
    positive_text = text
    for match in reversed(negated):
        positive_text = positive_text[: match.start()] + positive_text[match.end() :]
    if _CONTROLLED_EVIDENCE.search(positive_text) is not None:
        score += 4
    if _CONTROL_IDENTIFIER.search(positive_text) is not None:
        score += 2
    if negated:
        score -= 6
    if _LOW_AUTHORITY_EVIDENCE.search(text) is not None:
        score -= 4
    return score


def _requires_value_scope(
    question: str,
    *,
    evidence_texts: Sequence[str],
    publication: PublicationResult,
) -> bool:
    if (
        publication.status == "coverage_limited"
        or _question_requests_multiple_facts(question)
        or any(claim.relation != "fact" for claim in publication.claims)
    ):
        return False
    published_text = " ".join(
        part for claim in publication.claims for part in (claim.text, claim.value or "")
    )
    return (
        len(_query_tokens(question)) == 1
        and _contains_currency_value(published_text)
        and len(_distinct_currency_values(evidence_texts)) > 1
    )


def _question_requests_multiple_facts(question: str) -> bool:
    if _EXPLICIT_MULTI_FACT_QUESTION.search(question) is not None:
        return True
    all_tokens = [match.group(0).casefold() for match in _TOKEN.finditer(question)]
    content_tokens = [
        token for token in all_tokens if len(token) >= 2 and token not in _STOPWORDS
    ]
    if set(content_tokens) & _SINGLE_TOTAL_TERMS:
        return False
    if any(is_likely_plural(token) for token in content_tokens):
        return True
    return "and" in all_tokens and len(set(content_tokens)) > 1


def _question_prefers_structured_value(question: str) -> bool:
    return _STRUCTURED_VALUE_QUESTION.search(question) is not None


def _distinct_currency_values(
    evidence_texts: Sequence[str],
) -> set[tuple[str, Decimal]]:
    values: set[tuple[str, Decimal]] = set()
    for text in evidence_texts:
        matches = (
            *_CURRENCY_AMOUNT.finditer(text),
            *_SUFFIXED_CURRENCY_AMOUNT.finditer(text),
        )
        for match in matches:
            try:
                amount = Decimal(match.group("amount").replace(",", ""))
            except InvalidOperation:
                continue
            values.add((match.group("currency").upper(), amount))
    return values


def _contains_currency_value(text: str) -> bool:
    return (
        _CURRENCY_AMOUNT.search(text) is not None
        or _SUFFIXED_CURRENCY_AMOUNT.search(text) is not None
    )


def _material_value_anchor(
    text: str,
    *,
    assignment_token_sequences: tuple[tuple[str, ...], ...] | None = None,
    tokens: tuple[str, ...],
) -> tuple[int, int] | None:
    accepted_assignment_sequences = (
        _suffix_token_sequences(tokens)
        if assignment_token_sequences is None
        else assignment_token_sequences
    )
    token_set = set(tokens) | {
        token for sequence in accepted_assignment_sequences for token in sequence
    }
    if not token_set:
        return None

    token_spans = [
        (start, end)
        for token, start, end in _normalized_text_token_spans(text)
        if any(tokens_equivalent(token, query_token) for query_token in token_set)
    ]
    if not token_spans:
        return None

    assignments: list[tuple[int, int]] = []
    for _, token_end in token_spans:
        label_window_end = min(len(text), token_end + 64)
        boundary = re.search(r"[\n.;]", text[token_end:label_window_end])
        if boundary is not None:
            label_window_end = token_end + boundary.start()
        separator = re.search(
            r"(?P<strong>:|=|\s[\u2013\u2014-]\s)|"
            r"(?P<copula>\s+(?:is|are|was|were)\s+)",
            text[token_end:label_window_end],
            re.IGNORECASE,
        )
        if separator is None:
            continue
        separator_start = token_end + separator.start()
        label_start = (
            max(
                text.rfind("\n", 0, separator_start),
                text.rfind(";", 0, separator_start),
                text.rfind(".", 0, separator_start),
            )
            + 1
        )
        if not _assignment_label_matches_query(
            text[label_start:separator_start],
            token_sequences=accepted_assignment_sequences,
        ):
            continue
        value_start = token_end + separator.end()
        value_end = min(len(text), value_start + 80)
        value_boundary = re.search(r"[\n.;]", text[value_start:value_end])
        if value_boundary is not None:
            value_end = value_start + value_boundary.start()
        while value_end > value_start and text[value_end - 1].isspace():
            value_end -= 1
        if value_end <= value_start:
            continue
        strong_separator = separator.group("strong")
        strong_is_supported = strong_separator is not None and (
            strong_separator.strip() in {":", "="}
            or not text[token_end : token_end + separator.start()].strip()
        )
        if strong_is_supported or (
            strong_separator is None and _contains_assignment_value(text[value_start:value_end])
        ):
            assignments.append((label_start, value_end))
    if assignments:
        return min(assignments, key=lambda span: span[1] - span[0])
    if assignment_token_sequences is not None:
        return None

    signals = [
        *((match.span(), 120) for match in _CURRENCY_AMOUNT.finditer(text)),
        *((match.span(), 120) for match in _SUFFIXED_CURRENCY_AMOUNT.finditer(text)),
        *((match.span(), 120) for match in _PERCENT_VALUE.finditer(text)),
        *((match.span(), 120) for match in _EXPLICIT_VALUE_STATUS.finditer(text)),
        *((match.span(), 80) for match in _ISO_DATE_VALUE.finditer(text)),
        *((match.span(), 80) for match in _MONTH_DATE_VALUE.finditer(text)),
        *((match.span(), 80) for match in _EMAIL_VALUE.finditer(text)),
        *((match.span(), 80) for match in _URL_VALUE.finditer(text)),
        *((match.span(), 80) for match in _IDENTIFIER_VALUE.finditer(text)),
        *((match.span(), 48) for match in _FORMATTED_NUMBER.finditer(text)),
    ]
    candidates: list[tuple[int, tuple[int, int]]] = []
    for token_start, token_end in token_spans:
        for (signal_start, signal_end), maximum_distance in signals:
            distance = max(signal_start - token_end, token_start - signal_end, 0)
            if distance <= maximum_distance:
                candidates.append(
                    (
                        distance,
                        (min(token_start, signal_start), max(token_end, signal_end)),
                    )
                )
    if not candidates:
        return None
    _, anchor = min(candidates, key=lambda candidate: (candidate[0], candidate[1][0]))
    return anchor


def _assignment_label_matches_query(
    label: str, *, token_sequences: tuple[tuple[str, ...], ...]
) -> bool:
    label_tokens = tuple(
        token for token, _, _ in _normalized_text_token_spans(label) if token not in _STOPWORDS
    )
    if not label_tokens:
        return False
    return any(
        _query_token_sequences_match(label_tokens, token_sequence)
        for token_sequence in token_sequences
    )


def _query_token_sequences_match(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return len(left) == len(right) and all(
        tokens_equivalent(left_token, right_token)
        for left_token, right_token in zip(left, right, strict=True)
    )


def _contains_assignment_value(text: str) -> bool:
    return any(
        pattern.search(text) is not None
        for pattern in (
            _CURRENCY_AMOUNT,
            _SUFFIXED_CURRENCY_AMOUNT,
            _PERCENT_VALUE,
            _ISO_DATE_VALUE,
            _MONTH_DATE_VALUE,
            _EMAIL_VALUE,
            _URL_VALUE,
            _IDENTIFIER_VALUE,
            _EXPLICIT_VALUE_STATUS,
            _PLAIN_NUMBER,
        )
    )


def _contains_material_value_evidence(
    text: str,
    *,
    assignment_token_sequences: tuple[tuple[str, ...], ...] | None = None,
    tokens: tuple[str, ...],
) -> bool:
    return (
        _material_value_anchor(
            text,
            assignment_token_sequences=assignment_token_sequences,
            tokens=tokens,
        )
        is not None
    )


def _query_tokens(question: str) -> tuple[str, ...]:
    counts = Counter(
        token
        for token in (match.group(0).casefold() for match in _TOKEN.finditer(question))
        if len(token) >= 2 and token not in _STOPWORDS
    )
    return tuple(token for token, _ in counts.most_common(8))


def _suffix_token_sequences(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(tokens[index:] for index in range(len(tokens)))


def _query_assignment_token_sequences(
    question: str, *, tokens: tuple[str, ...]
) -> tuple[tuple[str, ...], ...]:
    """Derive field-label sequences without treating a trailing scope as the field."""

    verbal = _WHO_VERBAL_QUESTION.search(question)
    if verbal is not None:
        verb = verbal.group("verb").casefold()
        if verb not in {"are", "did", "does", "has", "is", "was", "were"}:
            return ()

    candidates: tuple[tuple[str, ...], ...] = _suffix_token_sequences(tokens)
    scope_matches = list(_FIELD_SCOPE_PREPOSITION.finditer(question))
    non_of_scopes = [scope for scope in scope_matches if scope.group(0).casefold() != "of"]
    for scope in (*non_of_scopes, *scope_matches):
        field_tokens = _query_tokens(question[: scope.start()])
        scope_tokens = _query_tokens(question[scope.end() :])
        if not field_tokens or not scope_tokens:
            continue
        candidates = (
            (field_tokens,)
            if "of" in field_tokens
            else (*_suffix_token_sequences(field_tokens), tokens)
        )
        break
    unique: list[tuple[str, ...]] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return tuple(unique)


def _merge_retrieved_blocks(*lanes: list[RetrievedBlock]) -> list[RetrievedBlock]:
    merged: list[RetrievedBlock] = []
    seen: set[UUID] = set()
    for lane in lanes:
        for candidate in lane:
            if candidate.block_id in seen:
                continue
            seen.add(candidate.block_id)
            merged.append(candidate)
    return merged


def _normalized_text_token_spans(text: str) -> list[tuple[str, int, int]]:
    return [
        (match.group(0).casefold(), match.start(), match.end())
        for match in _TOKEN.finditer(text)
        if len(match.group(0)) >= 2
    ]


def _select_passages(
    candidates: list[RetrievedBlock],
    *,
    assignment_token_sequences: tuple[tuple[str, ...], ...] | None = None,
    prefer_value_evidence: bool = False,
    require_token_match: bool = True,
    tokens: tuple[str, ...],
) -> tuple[PassageRecord, ...]:
    coverage_by_block = {
        candidate.block_id: _token_coverage(candidate.text, tokens=tokens)
        for candidate in candidates
    }
    strongest_coverage = max(coverage_by_block.values(), default=0)
    minimum_coverage = 2 if strongest_coverage >= 2 else int(require_token_match)
    material_by_block = {
        candidate.block_id: _material_value_anchor(
            candidate.text,
            assignment_token_sequences=assignment_token_sequences,
            tokens=tokens,
        )
        for candidate in candidates
    }
    enforce_material_evidence = prefer_value_evidence and any(
        anchor is not None for anchor in material_by_block.values()
    )
    if require_token_match and strongest_coverage == 0 and not enforce_material_evidence:
        return ()
    if enforce_material_evidence:
        minimum_coverage = 0
    selected: list[PassageRecord] = []
    per_source: Counter[UUID] = Counter()
    ranked_candidates = sorted(
        enumerate(candidates),
        key=lambda item: (
            coverage_by_block[item[1].block_id],
            int(prefer_value_evidence and material_by_block[item[1].block_id] is not None),
            -item[0],
        ),
        reverse=True,
    )
    for _, candidate in ranked_candidates:
        if coverage_by_block[candidate.block_id] < minimum_coverage:
            continue
        if enforce_material_evidence and material_by_block[candidate.block_id] is None:
            continue
        if per_source[candidate.source_file_id] >= _PASSAGE_PER_SOURCE_LIMIT:
            continue
        start, end = _excerpt_span(
            candidate.text,
            assignment_token_sequences=assignment_token_sequences,
            prefer_value_evidence=prefer_value_evidence,
            tokens=tokens,
        )
        if end <= start:
            continue
        selected.append(
            PassageRecord(
                block_id=candidate.block_id,
                drive_file_id=candidate.drive_file_id,
                end_exclusive_in_block=end,
                exact_quote=candidate.text[start:end],
                line_start_one_based=(
                    candidate.line_start_one_based + candidate.text.count("\n", 0, start)
                    if candidate.line_start_one_based is not None
                    else None
                ),
                origin_kind=candidate.origin_kind,
                page_index_zero_based=candidate.page_index_zero_based,
                path=candidate.path,
                printed_page_label=candidate.printed_page_label,
                source_name=candidate.source_name,
                start_in_block=start,
            )
        )
        per_source[candidate.source_file_id] += 1
        if len(selected) == _PASSAGE_LIMIT:
            break
    return tuple(selected)


def _model_passages(passages: tuple[PassageRecord, ...]) -> list[ModelPassage]:
    return [
        ModelPassage(
            block_id=passage.block_id,
            exact_quote=passage.exact_quote,
            locator_label=_locator_label(passage),
            source_name=passage.source_name,
        )
        for passage in passages
    ]


def _locator_label(passage: PassageRecord) -> str:
    if passage.origin_kind == "text_lines" and passage.line_start_one_based is not None:
        line_end = passage.line_start_one_based + passage.exact_quote.count("\n")
        return f"lines {passage.line_start_one_based}-{line_end}"
    page = passage.printed_page_label or str((passage.page_index_zero_based or 0) + 1)
    return f"page {page}"


def _evidence_blocks(
    candidates: list[RetrievedBlock],
    *,
    passages: tuple[PassageRecord, ...],
    context: QueryContext,
) -> list[EvidenceBlock]:
    included = {passage.block_id for passage in passages}
    blocks: list[EvidenceBlock] = []
    for candidate in candidates:
        if candidate.block_id not in included:
            continue
        origin: TextBlockOrigin | PdfBlockOrigin
        if candidate.origin_kind == "text_lines":
            assert candidate.line_start_one_based is not None
            origin = TextBlockOrigin(
                kind="text_lines", line_start_one_based=candidate.line_start_one_based
            )
        else:
            assert candidate.page_index_zero_based is not None
            origin = PdfBlockOrigin(
                kind="pdf_page",
                page_index_zero_based=candidate.page_index_zero_based,
                printed_page_label=candidate.printed_page_label,
            )
        blocks.append(
            EvidenceBlock(
                block_id=candidate.block_id,
                document_version_id=candidate.source_file_id,
                ingestion_run_id=context.run_id,
                normalized_text=candidate.text,
                origin=origin,
                workspace_id=context.workspace_id,
            )
        )
    return blocks


def _claim_records(
    publication: PublicationResult, candidates: list[RetrievedBlock]
) -> tuple[ClaimRecord, ...]:
    return tuple(
        ClaimRecord(
            citations=tuple(
                _publication_passage(citation, candidates) for citation in claim.citations
            ),
            claim_id=claim.claim_id,
            relation=claim.relation,
            text=claim.text,
            value=claim.value,
        )
        for claim in publication.claims
    )


def _publication_passage(
    passage: ApprovedCitation | RetrievedPassage, candidates: list[RetrievedBlock]
) -> PassageRecord:
    block_id = passage.block_id
    candidate = next(item for item in candidates if item.block_id == block_id)
    locator = passage.locator
    return PassageRecord(
        block_id=block_id,
        drive_file_id=candidate.drive_file_id,
        end_exclusive_in_block=locator.normalized_end_exclusive_in_block,
        exact_quote=passage.exact_quote,
        line_start_one_based=(
            locator.line_start_one_based if locator.kind == "text_lines" else None
        ),
        origin_kind=locator.kind,
        page_index_zero_based=(
            locator.page_index_zero_based if locator.kind == "pdf_page" else None
        ),
        path=candidate.path,
        printed_page_label=(locator.printed_page_label if locator.kind == "pdf_page" else None),
        normalized_value=(
            passage.normalized_value if isinstance(passage, ApprovedCitation) else None
        ),
        raw_value=passage.raw_value if isinstance(passage, ApprovedCitation) else None,
        role=passage.role if isinstance(passage, ApprovedCitation) else None,
        source_name=candidate.source_name,
        start_in_block=locator.normalized_start_in_block,
    )


def _publication_message(
    publication: PublicationResult, *, scope_required: bool = False
) -> str:
    if scope_required:
        return (
            "Multiple distinct values match this question. Ask with a scope—for example, "
            "the overall total or a named section."
        )
    if publication.status == "insufficient" and not publication.suppressed_claims:
        return (
            "Extent could not verify a specific answer. "
            "The strongest relevant passages are shown below."
        )
    if any(
        claim.proposed_relation == "conflict" and claim.relation == "fact"
        for claim in publication.claims
    ):
        return (
            "The authoritative controlled conclusion is stated first; a material "
            "lower-authority conflict is disclosed but was not adopted."
        )
    if any(
        claim.proposed_relation == "conflict" and claim.relation == "unclear"
        for claim in publication.claims
    ):
        return (
            "Conflicting evidence was verified, but authority is indeterminate; "
            "review is needed."
        )
    messages = {
        "evidence_supported": "Answer claims were verified against exact source text.",
        "changed": "A change was verified across distinct source evidence.",
        "conflict": "Conflicting values were verified across distinct source evidence.",
        "insufficient": "The model draft did not contain a claim Extent could verify.",
        "coverage_limited": (
            "No claim could be safely published within the available source coverage."
        ),
    }
    return messages[publication.status]


def _publication_passages(
    publication: PublicationResult,
    *,
    candidates: list[RetrievedBlock],
    retrieved: tuple[PassageRecord, ...],
) -> tuple[PassageRecord, ...]:
    if publication.retrieved_passages:
        return tuple(
            _publication_passage(item, candidates) for item in publication.retrieved_passages
        )
    if not publication.claims:
        return retrieved
    return ()


def _excerpt_span(
    text: str,
    *,
    assignment_token_sequences: tuple[tuple[str, ...], ...] | None = None,
    prefer_value_evidence: bool = False,
    tokens: tuple[str, ...],
) -> tuple[int, int]:
    best_span = (0, 0)
    best_score = (0, 0, 0)
    for line in re.finditer(r"[^\n]+", text):
        start, end = line.span()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        candidate_text = text[start:end]
        candidate_tokens = [
            token for token, _, _ in _normalized_text_token_spans(candidate_text)
        ]
        material_value = int(
            prefer_value_evidence
            and _contains_material_value_evidence(
                candidate_text,
                assignment_token_sequences=assignment_token_sequences,
                tokens=tokens,
            )
        )
        if (
            prefer_value_evidence
            and not material_value
            and _STRONG_ASSIGNMENT_SEPARATOR.search(candidate_text) is not None
        ):
            continue
        token_coverage = sum(
            any(tokens_equivalent(query_token, text_token) for text_token in candidate_tokens)
            for query_token in tokens
        )
        occurrence_count = sum(
            any(tokens_equivalent(query_token, text_token) for query_token in tokens)
            for text_token in candidate_tokens
        )
        score = (
            material_value,
            token_coverage,
            occurrence_count,
        )
        if score > best_score:
            best_score = score
            best_span = (start, end)
    start, end = best_span
    if end <= start:
        if prefer_value_evidence:
            return (0, 0)
        first_line = re.search(r"\S[^\n]*", text)
        if first_line is None:
            return (0, 0)
        start, end = first_line.span()
    if end - start <= _PASSAGE_EXCERPT_LIMIT:
        return start, end

    anchor = (
        _material_value_anchor(
            text[start:end],
            assignment_token_sequences=assignment_token_sequences,
            tokens=tokens,
        )
        if prefer_value_evidence
        else None
    )
    if anchor is None:
        positions = [
            token_start
            for text_token, token_start, _ in _normalized_text_token_spans(text[start:end])
            if any(tokens_equivalent(query_token, text_token) for query_token in tokens)
        ]
        hit = min(positions, default=0)
        anchor = (hit, hit)
    anchor_start, anchor_end = start + anchor[0], start + anchor[1]
    narrowed_start = max(
        start,
        min(anchor_start - 80, end - _PASSAGE_EXCERPT_LIMIT),
    )
    narrowed_end = min(end, narrowed_start + _PASSAGE_EXCERPT_LIMIT)
    if anchor_end > narrowed_end:
        narrowed_end = min(end, anchor_end + 80)
        narrowed_start = max(start, narrowed_end - _PASSAGE_EXCERPT_LIMIT)

    if narrowed_start > start:
        next_space = text.find(" ", narrowed_start, min(narrowed_start + 24, anchor_start))
        if next_space >= 0:
            narrowed_start = next_space + 1
    if narrowed_end < end:
        previous_space = text.rfind(" ", max(anchor_end, narrowed_end - 24), narrowed_end)
        if previous_space >= 0:
            narrowed_end = previous_space
    return narrowed_start, narrowed_end


def _token_coverage(text: str, *, tokens: tuple[str, ...]) -> int:
    text_tokens = {token for token, _, _ in _normalized_text_token_spans(text)}
    return sum(
        any(tokens_equivalent(query_token, text_token) for text_token in text_tokens)
        for query_token in tokens
    )


def project_question_result(result: StoredQuestionResult) -> WorkspaceQuestionResultView:
    policy_version = (
        CLARIFICATION_POLICY_VERSION
        if _is_legacy_clarification_result(result)
        else result.policy_version
    )
    return WorkspaceQuestionResultView(
        answer_id=result.answer_id,
        claims=[
            WorkspaceApprovedClaimView(
                citations=[_passage_view(citation) for citation in claim.citations],
                claim_id=claim.claim_id,
                relation=claim.relation,  # type: ignore[arg-type]
                text=claim.text,
                value=claim.value,
            )
            for claim in result.claims
        ],
        coverage_gap_reasons=result.coverage_gap_reasons,  # type: ignore[arg-type]
        created_at=result.created_at,
        generation_status=result.generation_status,  # type: ignore[arg-type]
        message=result.message,
        passages=[_passage_view(passage) for passage in result.passages],
        policy_version=policy_version,  # type: ignore[arg-type]
        question=result.question,
        question_id=result.question_id,
        status=result.status,  # type: ignore[arg-type]
    )


def _is_legacy_clarification_result(result: StoredQuestionResult) -> bool:
    if (
        result.policy_version != "publication-policy-v1"
        or result.generation_status != "completed"
        or result.status != "insufficient"
        or result.claims
    ):
        return False
    return result.message == _CLARIFICATION_MESSAGE or result.message.startswith(
        (
            "Name one labeled field to extract",
            "Ask for one labeled field at a time",
            "Use a shorter label for one field to extract",
        )
    )


def _passage_view(passage: PassageRecord) -> WorkspaceEvidencePassageView:
    return WorkspaceEvidencePassageView(
        block_id=passage.block_id,
        drive_file_id=passage.drive_file_id,
        end_exclusive_in_block=passage.end_exclusive_in_block,
        exact_quote=passage.exact_quote,
        line_start_one_based=passage.line_start_one_based,
        normalized_value=passage.normalized_value,
        origin_kind=passage.origin_kind,  # type: ignore[arg-type]
        page_index_zero_based=passage.page_index_zero_based,
        path=list(passage.path),
        printed_page_label=passage.printed_page_label,
        raw_value=passage.raw_value,
        role=passage.role,  # type: ignore[arg-type]
        source_name=passage.source_name,
        start_in_block=passage.start_in_block,
    )
