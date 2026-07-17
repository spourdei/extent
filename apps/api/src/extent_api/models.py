"""Strict public read models for the React/FastAPI boundary."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

BoundedText = Annotated[str, Field(min_length=1, max_length=2_000)]
ShortText = Annotated[str, Field(min_length=1, max_length=280)]
Identifier = UUID


class ApiModel(BaseModel):
    """All public models are immutable, camelCase on the wire, and fail on extras."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class HealthResponse(ApiModel):
    service: Literal["extent-api"] = "extent-api"
    status: Literal["ok"] = "ok"
    version: str


class CitationContext(ApiModel):
    citation_id: Identifier
    file_name: Annotated[str, Field(min_length=1, max_length=240)]
    locator_label: Annotated[str, Field(min_length=1, max_length=80)]
    observed_at: AwareDatetime
    passage_after: Annotated[str, Field(max_length=221)]
    passage_before: Annotated[str, Field(max_length=221)]


class ContextSourceCount(ApiModel):
    candidate_chunk_count: Annotated[int, Field(ge=0)]
    document_version_id: Identifier
    included_chunk_count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def included_cannot_exceed_candidates(self) -> Self:
        if self.included_chunk_count > self.candidate_chunk_count:
            raise ValueError("included chunk count cannot exceed candidate count")
        return self


class ExcludedContextChunk(ApiModel):
    chunk_id: Identifier
    reason_code: Annotated[str, Field(min_length=1, max_length=80)]


class ContextManifest(ApiModel):
    active_claim_ids: Annotated[list[Identifier], Field(max_length=12)]
    active_turn_ids: Annotated[list[Identifier], Field(max_length=4)]
    candidate_chunk_ids: Annotated[list[Identifier], Field(max_length=40)]
    context_policy_version: Annotated[str, Field(min_length=1, max_length=80)]
    excluded_chunks: Annotated[list[ExcludedContextChunk], Field(max_length=40)]
    included_chunk_ids: Annotated[list[Identifier], Field(max_length=12)]
    original_message_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    selection_ordering: Literal["retrieval_rank_then_source_cap"]
    snapshot_id: Identifier
    source_counts: Annotated[list[ContextSourceCount], Field(max_length=40)]
    token_budget: Annotated[int, Field(gt=0, le=16_000)]

    @model_validator(mode="after")
    def candidates_are_partitioned(self) -> Self:
        candidates = set(self.candidate_chunk_ids)
        included = set(self.included_chunk_ids)
        excluded = {item.chunk_id for item in self.excluded_chunks}
        if len(candidates) != len(self.candidate_chunk_ids):
            raise ValueError("candidate chunk ids must be unique")
        if included & excluded or included | excluded != candidates:
            raise ValueError("context candidates must be partitioned into included or excluded")
        if sum(item.candidate_chunk_count for item in self.source_counts) != len(candidates):
            raise ValueError("per-source candidate counts must match the manifest")
        if sum(item.included_chunk_count for item in self.source_counts) != len(included):
            raise ValueError("per-source included counts must match the manifest")
        return self


class TextLineLocator(ApiModel):
    normalized_end_exclusive: Annotated[int, Field(ge=0)]
    normalized_start: Annotated[int, Field(ge=0)]
    raw_end_exclusive: Annotated[int, Field(ge=0)]
    raw_start: Annotated[int, Field(ge=0)]
    kind: Literal["text_lines"]
    line_end_one_based_inclusive: Annotated[int, Field(gt=0)]
    line_start_one_based: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> Self:
        if self.raw_end_exclusive <= self.raw_start:
            raise ValueError("raw citation end must follow its start")
        if self.normalized_end_exclusive <= self.normalized_start:
            raise ValueError("normalized citation end must follow its start")
        if self.line_end_one_based_inclusive < self.line_start_one_based:
            raise ValueError("text locator end line cannot precede its start line")
        return self


class PdfPageLocator(ApiModel):
    normalized_end_exclusive: Annotated[int, Field(ge=0)]
    normalized_start: Annotated[int, Field(ge=0)]
    raw_end_exclusive: Annotated[int, Field(ge=0)]
    raw_start: Annotated[int, Field(ge=0)]
    kind: Literal["pdf_page"]
    page_index_zero_based: Annotated[int, Field(ge=0)]
    printed_page_label: Annotated[str, Field(min_length=1, max_length=40)] | None

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> Self:
        if self.raw_end_exclusive <= self.raw_start:
            raise ValueError("raw citation end must follow its start")
        if self.normalized_end_exclusive <= self.normalized_start:
            raise ValueError("normalized citation end must follow its start")
        return self


SourceLocator = Annotated[TextLineLocator | PdfPageLocator, Field(discriminator="kind")]


class Citation(ApiModel):
    citation_id: Identifier
    document_version_id: Identifier
    locator: SourceLocator
    quote: BoundedText
    source_block_id: Identifier

    @model_validator(mode="after")
    def quote_matches_normalized_span(self) -> Self:
        length = self.locator.normalized_end_exclusive - self.locator.normalized_start
        if length != len(self.quote):
            raise ValueError("normalized citation range must have the same length as the quote")
        return self


class MoneyValue(ApiModel):
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    kind: Literal["money"]
    literal: Annotated[str, Field(min_length=1, max_length=120)]
    value_minor: Annotated[str, Field(pattern=r"^-?(?:0|[1-9]\d*)$")]


class Applicability(ApiModel):
    effective_from: date | None
    effective_to: date | None
    entity: Annotated[str, Field(min_length=1, max_length=160)]
    field: Annotated[str, Field(min_length=1, max_length=120)]
    period_label: Annotated[str, Field(min_length=1, max_length=120)]
    scope: Annotated[str, Field(min_length=1, max_length=240)]


class ExtractedLineage(ApiModel):
    applicability: Applicability
    citation_ids: Annotated[list[Identifier], Field(min_length=1, max_length=12)]
    document_version_id: Identifier
    kind: Literal["extracted"]
    normalized_value: MoneyValue


class PublishedClaim(ApiModel):
    claim_id: Identifier
    kind: Literal["extracted"]
    lineage: ExtractedLineage
    relation_kind: Literal["fact"]
    text: Annotated[str, Field(min_length=1, max_length=800)]
    citation_ids: Annotated[list[Identifier], Field(min_length=1, max_length=12)]
    status: Literal["published"]

    @model_validator(mode="after")
    def citations_match_lineage(self) -> Self:
        if set(self.citation_ids) != set(self.lineage.citation_ids):
            raise ValueError("published citations must exactly match lineage citations")
        return self


class ExcludedEvidence(ApiModel):
    reason_code: Annotated[str, Field(min_length=1, max_length=80)]
    source_block_id: Identifier


class ProposedClaimRef(ApiModel):
    cited_block_ids: Annotated[list[Identifier], Field(min_length=1, max_length=12)]
    claim_id: Identifier


class SuppressedClaimRef(ApiModel):
    claim_id: Identifier
    reason_code: Annotated[str, Field(min_length=1, max_length=80)]


class VerifierVerdict(ApiModel):
    claim_id: Identifier
    verdict: Literal["supported", "partial", "unsupported", "contradicted"]


class EvidenceFunnel(ApiModel):
    candidate_block_ids: Annotated[list[Identifier], Field(max_length=40)]
    eligible_claim_ids: Annotated[list[Identifier], Field(max_length=12)]
    excluded_evidence: Annotated[list[ExcludedEvidence], Field(max_length=40)]
    included_block_ids: Annotated[list[Identifier], Field(max_length=12)]
    proposed_claims: Annotated[list[ProposedClaimRef], Field(max_length=12)]
    published_claim_ids: Annotated[list[Identifier], Field(max_length=12)]
    suppressed_claims: Annotated[list[SuppressedClaimRef], Field(max_length=12)]
    verifier_verdicts: Annotated[list[VerifierVerdict], Field(max_length=12)]

    @model_validator(mode="after")
    def publication_is_monotone(self) -> Self:
        candidates = set(self.candidate_block_ids)
        included = set(self.included_block_ids)
        excluded = {item.source_block_id for item in self.excluded_evidence}
        if included | excluded != candidates or included & excluded:
            raise ValueError("evidence candidates must be partitioned")
        proposals = {item.claim_id for item in self.proposed_claims}
        eligible = set(self.eligible_claim_ids)
        verdicts = {item.claim_id: item.verdict for item in self.verifier_verdicts}
        published = set(self.published_claim_ids)
        suppressed = {item.claim_id for item in self.suppressed_claims}
        if not eligible <= proposals or set(verdicts) != eligible:
            raise ValueError("eligible claims and verifier verdicts must narrow proposals")
        if any(verdicts.get(claim_id) != "supported" for claim_id in published):
            raise ValueError("only supported claims may be published")
        if published & suppressed or published | suppressed != proposals:
            raise ValueError("every proposal must be published or suppressed")
        return self


CoverageGap = Literal[
    "processing",
    "failed",
    "unsupported",
    "inaccessible",
    "capped",
    "unknown_branch",
    "unstable",
    "unsafe_to_parse",
]


class CoverageManifest(ApiModel):
    capped: Annotated[int, Field(ge=0)]
    discovered: Annotated[int, Field(ge=0)]
    discovery_complete: bool
    failed: Annotated[int, Field(ge=0)]
    gap_reasons: list[CoverageGap]
    inaccessible: Annotated[int, Field(ge=0)]
    processing: Annotated[int, Field(ge=0)]
    ready: Annotated[int, Field(ge=0)]
    unsafe_to_parse: Annotated[int, Field(ge=0)]
    unknown_branches: Annotated[int, Field(ge=0)]
    unstable: Annotated[int, Field(ge=0)]
    unsupported: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def counts_are_complete(self) -> Self:
        accounted = (
            self.capped
            + self.failed
            + self.inaccessible
            + self.processing
            + self.ready
            + self.unsafe_to_parse
            + self.unknown_branches
            + self.unstable
            + self.unsupported
        )
        if accounted != self.discovered:
            raise ValueError("coverage counts must account for every discovered source")
        return self


class Freshness(ApiModel):
    checked_at: AwareDatetime
    status: Literal["fresh", "refreshing", "stale", "unknown"]


class ExtentRevision(ApiModel):
    coverage: CoverageManifest
    freshness: Freshness
    observed_version_count: Annotated[int, Field(ge=0)]
    snapshot_id: Identifier
    sync_ended_at: AwareDatetime
    sync_started_at: AwareDatetime

    @model_validator(mode="after")
    def sync_is_ordered(self) -> Self:
        if self.sync_ended_at < self.sync_started_at:
            raise ValueError("revision sync cannot end before it starts")
        return self


class PublishedTerminal(ApiModel):
    terminal_at: AwareDatetime
    trace_id: Identifier
    answer_id: Identifier
    status: Literal[
        "evidence_supported",
        "changed",
        "conflict",
        "not_comparable",
        "precedence_unknown",
    ]


class PublishedAnswerView(ApiModel):
    answer_id: Identifier
    citations: Annotated[list[Citation], Field(min_length=1, max_length=6)]
    claims: Annotated[list[PublishedClaim], Field(min_length=1, max_length=3)]
    funnel: EvidenceFunnel
    revision: ExtentRevision
    terminal: PublishedTerminal
    trace_id: Identifier

    @model_validator(mode="after")
    def references_resolve(self) -> Self:
        if self.terminal.answer_id != self.answer_id or self.terminal.trace_id != self.trace_id:
            raise ValueError("answer and terminal identifiers must match")
        claim_ids = {claim.claim_id for claim in self.claims}
        if claim_ids != set(self.funnel.published_claim_ids):
            raise ValueError("rendered claims must exactly match funnel publication output")
        citation_ids = {citation.citation_id for citation in self.citations}
        referenced_ids = {item for claim in self.claims for item in claim.citation_ids}
        if citation_ids != referenced_ids:
            raise ValueError("all answer citations must resolve and be used")
        if any(
            citation.source_block_id not in self.funnel.included_block_ids
            for citation in self.citations
        ):
            raise ValueError("published citations must descend from included evidence")
        return self


QueryStage = Literal[
    "accepted",
    "authorizing",
    "interpreting",
    "cache_check",
    "contextualizing",
    "retrieving",
    "composing",
    "structural_validation",
    "verifying",
    "publishing",
    "complete",
]


class QueryExecution(ApiModel):
    acknowledgement_copy_key: Literal["evidence_acknowledgement"]
    context_manifest: ContextManifest | None
    replayed: bool
    stages: Annotated[list[QueryStage], Field(min_length=3, max_length=11)]
    view: PublishedAnswerView

    @model_validator(mode="after")
    def stages_are_bounded(self) -> Self:
        if self.stages[0] != "accepted" or self.stages[-1] != "complete":
            raise ValueError("execution must start accepted and end complete")
        if len(set(self.stages)) != len(self.stages):
            raise ValueError("execution stages cannot repeat")
        return self


class WorkspaceSource(ApiModel):
    document_version_id: Identifier
    evaluated: bool
    file_name: Annotated[str, Field(min_length=1, max_length=240)]
    observed_at: AwareDatetime
    reason: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    selected: bool
    status: Literal["ready", "unsupported"]

    @model_validator(mode="after")
    def unsupported_sources_are_not_evaluated(self) -> Self:
        if self.status == "unsupported" and (
            self.evaluated or self.selected or self.reason is None
        ):
            raise ValueError("unsupported sample sources require a reason and no evaluation")
        if self.status == "ready" and self.reason is not None:
            raise ValueError("ready sample sources cannot have an unavailable reason")
        return self


class WorkspaceSummary(ApiModel):
    name: Annotated[str, Field(min_length=1, max_length=160)]
    revision_label: Annotated[str, Field(min_length=1, max_length=80)] | None
    sample_label: Annotated[str, Field(min_length=1, max_length=80)]
    sources: Annotated[list[WorkspaceSource], Field(max_length=100)]


class SampleWorkspaceProjection(ApiModel):
    citation_contexts: Annotated[list[CitationContext], Field(max_length=6)]
    execution: QueryExecution
    question: Annotated[str, Field(min_length=1, max_length=1_000)]
    workspace: WorkspaceSummary

    @model_validator(mode="after")
    def contexts_resolve_and_payload_is_bounded(self) -> Self:
        citation_ids = {citation.citation_id for citation in self.execution.view.citations}
        context_ids = {context.citation_id for context in self.citation_contexts}
        if context_ids != citation_ids:
            raise ValueError("citation contexts must resolve exactly to published citations")
        payload = self.model_dump_json(by_alias=True).encode()
        if len(payload) > 65_536:
            raise ValueError("sample projection exceeds its initial-render byte budget")
        return self


def utc_timestamp(value: str) -> datetime:
    """Small typed helper retained for fixtures and future factories."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an offset")
    return parsed
