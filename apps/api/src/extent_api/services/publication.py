"""Deterministic authorization of model-proposed claims against persisted evidence.

The model may propose answer copy and citations.  This module is the smaller, stricter
boundary that decides whether any of that material may become product output.  It has no
provider, database, or HTTP dependencies so the query service and frozen eval runner can
share the exact same policy.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from extent_api.models import CoverageGap, CoverageManifest

_NUMBER_TOKEN = re.compile(
    r"(?<![\w\d])(?P<sign>[+-])?(?:[$€£])?"
    r"(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)(?P<percent>%?)(?![\w])"
)
_CURRENCY_SYMBOL = re.compile(r"[$€£]")
_DATE_TOKEN = re.compile(
    r"\b(?P<iso>\d{4}-\d{2}-\d{2})\b"
    r"|\b(?P<slash>\d{1,2}/\d{1,2}/\d{4})\b"
    r"|\b(?P<month>"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})\b",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")
_UNSAFE_EVIDENCE_INSTRUCTION = re.compile(
    r"\b(?:ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
    r"disregard\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
    r"system\s+prompt|you\s+are\s+chatgpt)\b",
    re.IGNORECASE,
)

Relation = Literal["fact", "change", "conflict", "unclear"]
EvidenceRole = Literal["support", "before", "after", "left", "right"]
PublicationStatus = Literal[
    "evidence_supported",
    "changed",
    "conflict",
    "insufficient",
    "coverage_limited",
]
SuppressionReason = Literal[
    "ambiguous_exact_quote",
    "claim_value_not_evidenced",
    "evidence_not_in_retrieval_set",
    "evidence_outside_authorized_run",
    "exact_quote_not_found",
    "run_not_terminal",
    "unsafe_evidence_instruction",
    "unknown_evidence_block",
    "unsupported_claim_token",
]
PolicyNote = Literal[
    "change_requires_distinct_ordered_values",
    "comparison_applicability_mismatch",
    "comparison_requires_distinct_branches",
    "conflict_requires_incompatible_values",
]


class PublicationModel(BaseModel):
    """Strict immutable models for the internal publication boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TextBlockOrigin(PublicationModel):
    kind: Literal["text_lines"]
    line_start_one_based: Annotated[int, Field(gt=0)]


class PdfBlockOrigin(PublicationModel):
    kind: Literal["pdf_page"]
    page_index_zero_based: Annotated[int, Field(ge=0)]
    printed_page_label: Annotated[str, Field(min_length=1, max_length=40)] | None = None


BlockOrigin = Annotated[TextBlockOrigin | PdfBlockOrigin, Field(discriminator="kind")]


class EvidenceBlock(PublicationModel):
    """The persisted evidence fields the publication policy is allowed to trust."""

    block_id: UUID
    document_version_id: UUID
    ingestion_run_id: UUID
    normalized_text: Annotated[str, Field(min_length=1, max_length=50_000)]
    origin: BlockOrigin
    workspace_id: UUID


class DraftEvidenceRef(PublicationModel):
    """A model-proposed evidence branch; all material fields are rechecked below."""

    block_id: UUID
    effective_date: date | None = None
    entity: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    exact_quote: Annotated[str, Field(min_length=1, max_length=2_000)]
    field: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    scope: Annotated[str, Field(min_length=1, max_length=240)] | None = None
    value: Annotated[str, Field(min_length=1, max_length=120)] | None = None


class ClaimDraft(PublicationModel):
    claim_id: UUID
    effective_date: date | None = None
    evidence: Annotated[list[DraftEvidenceRef], Field(min_length=1, max_length=2)]
    relation: Relation
    text: Annotated[str, Field(min_length=1, max_length=800)]
    value: Annotated[str, Field(min_length=1, max_length=120)] | None = None


class AnswerDraft(PublicationModel):
    canonical_question: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    claims: Annotated[list[ClaimDraft], Field(max_length=3)]
    needs_clarification: Annotated[str, Field(min_length=1, max_length=400)] | None = None
    routing_intents: Annotated[
        list[
            Literal[
                "aggregate",
                "compare",
                "completeness",
                "exceptions",
                "filter",
                "group",
                "join",
                "list",
                "lookup",
                "order",
                "summary",
            ]
        ],
        Field(max_length=8),
    ] = []
    routing_mode: Literal["direct", "exhaustive", "mixed", "structured"] | None = None
    summary: Annotated[str, Field(min_length=1, max_length=2_000)]

    @model_validator(mode="after")
    def claim_ids_are_unique(self) -> Self:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("draft claim ids must be unique")
        if self.needs_clarification is not None and self.claims:
            raise ValueError("a clarification draft cannot contain claims")
        return self


class PublicationContext(PublicationModel):
    coverage: CoverageManifest
    included_block_ids: Annotated[list[UUID], Field(max_length=10)]
    ingestion_run_id: UUID
    run_terminal: bool
    workspace_id: UUID

    @model_validator(mode="after")
    def included_blocks_are_unique(self) -> Self:
        if len(set(self.included_block_ids)) != len(self.included_block_ids):
            raise ValueError("included block ids must be unique")
        return self


class ResolvedTextLocator(PublicationModel):
    kind: Literal["text_lines"]
    line_end_one_based_inclusive: Annotated[int, Field(gt=0)]
    line_start_one_based: Annotated[int, Field(gt=0)]
    normalized_end_exclusive_in_block: Annotated[int, Field(gt=0)]
    normalized_start_in_block: Annotated[int, Field(ge=0)]


class ResolvedPdfLocator(PublicationModel):
    kind: Literal["pdf_page"]
    normalized_end_exclusive_in_block: Annotated[int, Field(gt=0)]
    normalized_start_in_block: Annotated[int, Field(ge=0)]
    page_index_zero_based: Annotated[int, Field(ge=0)]
    printed_page_label: Annotated[str, Field(min_length=1, max_length=40)] | None = None


ResolvedLocator = Annotated[
    ResolvedTextLocator | ResolvedPdfLocator, Field(discriminator="kind")
]


class ApprovedCitation(PublicationModel):
    block_id: UUID
    document_version_id: UUID
    exact_quote: Annotated[str, Field(min_length=1, max_length=2_000)]
    locator: ResolvedLocator
    normalized_value: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    raw_value: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    role: EvidenceRole


class ApprovedClaim(PublicationModel):
    citations: Annotated[list[ApprovedCitation], Field(min_length=1, max_length=2)]
    claim_id: UUID
    policy_notes: Annotated[list[PolicyNote], Field(max_length=3)]
    proposed_relation: Relation
    relation: Relation
    text: Annotated[str, Field(min_length=1, max_length=800)]
    value: Annotated[str, Field(min_length=1, max_length=120)] | None = None


class SuppressedClaim(PublicationModel):
    claim_id: UUID
    reason_codes: Annotated[list[SuppressionReason], Field(min_length=1, max_length=8)]


class RetrievedPassage(PublicationModel):
    block_id: UUID
    document_version_id: UUID
    exact_quote: Annotated[str, Field(min_length=1, max_length=2_000)]
    locator: ResolvedLocator


class PublicationResult(PublicationModel):
    claims: Annotated[list[ApprovedClaim], Field(max_length=3)]
    coverage_gap_reasons: list[CoverageGap]
    policy_version: Literal["publication-policy-v1"] = "publication-policy-v1"
    retrieved_passages: Annotated[list[RetrievedPassage], Field(max_length=6)]
    status: PublicationStatus
    suppressed_claims: Annotated[list[SuppressedClaim], Field(max_length=3)]


def authorize_answer_draft(
    draft: AnswerDraft,
    *,
    blocks: Sequence[EvidenceBlock],
    context: PublicationContext,
) -> PublicationResult:
    """Narrow a model draft into approved claims or a typed, coverage-aware non-answer."""

    blocks_by_id = {block.block_id: block for block in blocks}
    included_block_ids = set(context.included_block_ids)
    approved: list[ApprovedClaim] = []
    suppressed: list[SuppressedClaim] = []
    safe_passages: dict[tuple[UUID, str], RetrievedPassage] = {}

    for claim in draft.claims:
        resolved_branches: list[tuple[RetrievedPassage, DraftEvidenceRef]] = []
        reasons: set[SuppressionReason] = set()

        if not context.run_terminal:
            reasons.add("run_not_terminal")

        for evidence_ref in claim.evidence:
            block = blocks_by_id.get(evidence_ref.block_id)
            if block is None:
                reasons.add("unknown_evidence_block")
                continue
            if (
                block.workspace_id != context.workspace_id
                or block.ingestion_run_id != context.ingestion_run_id
            ):
                reasons.add("evidence_outside_authorized_run")
                continue
            if block.block_id not in included_block_ids:
                reasons.add("evidence_not_in_retrieval_set")
                continue

            citation, quote_failure = _resolve_exact_quote(block, evidence_ref.exact_quote)
            if quote_failure is not None:
                reasons.add(quote_failure)
                continue
            assert citation is not None
            if _UNSAFE_EVIDENCE_INSTRUCTION.search(block.normalized_text) is not None:
                reasons.add("unsafe_evidence_instruction")
                continue
            if not any(
                existing.block_id == citation.block_id
                and existing.exact_quote == citation.exact_quote
                for existing, _ in resolved_branches
            ):
                resolved_branches.append((citation, evidence_ref))
            safe_passages[(citation.block_id, citation.exact_quote)] = RetrievedPassage(
                block_id=citation.block_id,
                document_version_id=citation.document_version_id,
                exact_quote=citation.exact_quote,
                locator=citation.locator,
            )

            if evidence_ref.value is not None and not _literal_is_supported(
                evidence_ref.value, evidence_ref.exact_quote
            ):
                reasons.add("claim_value_not_evidenced")
            if evidence_ref.effective_date is not None and not _date_is_supported(
                evidence_ref.effective_date, evidence_ref.exact_quote
            ):
                reasons.add("claim_value_not_evidenced")

        supported_text = "\n".join(citation.exact_quote for citation, _ in resolved_branches)
        if resolved_branches:
            if not _material_tokens_are_supported(claim.text, supported_text):
                reasons.add("unsupported_claim_token")
            if claim.value is not None and not _literal_is_supported(
                claim.value, supported_text
            ):
                reasons.add("claim_value_not_evidenced")
            if claim.effective_date is not None and not _date_is_supported(
                claim.effective_date, supported_text
            ):
                reasons.add("claim_value_not_evidenced")

        if reasons:
            suppressed.append(
                SuppressedClaim(claim_id=claim.claim_id, reason_codes=sorted(reasons))
            )
            continue

        relation, policy_notes = _authorize_relation(
            claim, [citation for citation, _ in resolved_branches]
        )
        approved.append(
            ApprovedClaim(
                citations=_approved_citations(claim, resolved_branches, relation=relation),
                claim_id=claim.claim_id,
                policy_notes=policy_notes,
                proposed_relation=claim.relation,
                relation=relation,
                text=claim.text,
                value=claim.value,
            )
        )

    gaps = coverage_gaps(context.coverage)
    if approved:
        status = _published_status(approved)
        retrieved_passages: list[RetrievedPassage] = []
    else:
        status = "coverage_limited" if gaps or not context.run_terminal else "insufficient"
        retrieved_passages = list(safe_passages.values())[:6]

    return PublicationResult(
        claims=approved,
        coverage_gap_reasons=gaps,
        retrieved_passages=retrieved_passages,
        status=status,
        suppressed_claims=suppressed,
    )


def _resolve_exact_quote(
    block: EvidenceBlock, exact_quote: str
) -> tuple[RetrievedPassage | None, SuppressionReason | None]:
    quote_start = block.normalized_text.find(exact_quote)
    if quote_start < 0:
        return None, "exact_quote_not_found"
    if block.normalized_text.find(exact_quote, quote_start + 1) >= 0:
        return None, "ambiguous_exact_quote"

    quote_end = quote_start + len(exact_quote)
    if block.origin.kind == "pdf_page":
        locator: ResolvedLocator = ResolvedPdfLocator(
            kind="pdf_page",
            normalized_end_exclusive_in_block=quote_end,
            normalized_start_in_block=quote_start,
            page_index_zero_based=block.origin.page_index_zero_based,
            printed_page_label=block.origin.printed_page_label,
        )
    else:
        line_start = block.origin.line_start_one_based + block.normalized_text.count(
            "\n", 0, quote_start
        )
        line_end = line_start + exact_quote.count("\n")
        if exact_quote.endswith("\n"):
            line_end -= 1
        locator = ResolvedTextLocator(
            kind="text_lines",
            line_end_one_based_inclusive=max(line_start, line_end),
            line_start_one_based=line_start,
            normalized_end_exclusive_in_block=quote_end,
            normalized_start_in_block=quote_start,
        )

    return (
        RetrievedPassage(
            block_id=block.block_id,
            document_version_id=block.document_version_id,
            exact_quote=exact_quote,
            locator=locator,
        ),
        None,
    )


def _approved_citations(
    claim: ClaimDraft,
    branches: list[tuple[RetrievedPassage, DraftEvidenceRef]],
    *,
    relation: Relation,
) -> list[ApprovedCitation]:
    if relation == "change":
        branches = sorted(
            branches,
            key=lambda item: item[1].effective_date or date.max,
        )
        roles: list[EvidenceRole] = ["before", "after"]
    elif relation == "conflict" or (relation == "unclear" and len(branches) == 2):
        roles = ["left", "right"]
    else:
        roles = ["support"] * len(branches)

    return [
        ApprovedCitation(
            block_id=citation.block_id,
            document_version_id=citation.document_version_id,
            exact_quote=citation.exact_quote,
            locator=citation.locator,
            normalized_value=_canonical_value(reference.value),
            raw_value=reference.value,
            role=roles[index],
        )
        for index, (citation, reference) in enumerate(branches)
    ]


def _authorize_relation(
    claim: ClaimDraft, citations: Sequence[RetrievedPassage]
) -> tuple[Relation, list[PolicyNote]]:
    if claim.relation not in {"change", "conflict"}:
        return claim.relation, []

    refs = claim.evidence
    if (
        len(refs) != 2
        or len({item.block_id for item in refs}) != 2
        or len({item.document_version_id for item in citations}) != 2
    ):
        return "unclear", ["comparison_requires_distinct_branches"]

    applicability = {
        (_comparison_key(ref.entity), _comparison_key(ref.field), _comparison_key(ref.scope))
        for ref in refs
    }
    if None in next(iter(applicability), ()) or len(applicability) != 1:
        return "unclear", ["comparison_applicability_mismatch"]

    values = [_comparison_key(ref.value) for ref in refs]
    if None in values or values[0] == values[1]:
        note: PolicyNote = (
            "change_requires_distinct_ordered_values"
            if claim.relation == "change"
            else "conflict_requires_incompatible_values"
        )
        return "unclear", [note]

    if claim.relation == "change":
        dates = [ref.effective_date for ref in refs]
        if None in dates or dates[0] == dates[1]:
            return "unclear", ["change_requires_distinct_ordered_values"]

    return claim.relation, []


def _comparison_key(value: str | None) -> str | None:
    if value is None:
        return None
    return _WHITESPACE.sub(" ", value.strip()).casefold()


def _canonical_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    date_match = _DATE_TOKEN.fullmatch(stripped)
    if date_match is not None:
        parsed_date = _parse_date_match(date_match)
        if parsed_date is not None:
            return parsed_date.isoformat()
    numeric_match = _NUMBER_TOKEN.fullmatch(stripped)
    if numeric_match is not None:
        return _canonical_number(numeric_match)
    return _comparison_key(value)


def _number_tokens(value: str) -> set[str]:
    return {_canonical_number(match) for match in _NUMBER_TOKEN.finditer(value)}


def _canonical_number(match: re.Match[str]) -> str:
    numeric = match.group("number").replace(",", "")
    if "." in numeric:
        numeric = numeric.rstrip("0").rstrip(".")
    numeric = numeric.lstrip("0") or "0"
    sign = match.group("sign") or ""
    percent = match.group("percent")
    return f"{sign}{numeric}{percent}"


def _literal_is_supported(literal: str, evidence: str) -> bool:
    date_match = _DATE_TOKEN.fullmatch(literal.strip())
    if date_match is not None:
        parsed_date = _parse_date_match(date_match)
        return parsed_date is not None and _date_is_supported(parsed_date, evidence)
    tokens = _number_tokens(literal)
    if tokens:
        currency_symbols = set(_CURRENCY_SYMBOL.findall(literal))
        return tokens <= _number_tokens(evidence) and currency_symbols <= set(
            _CURRENCY_SYMBOL.findall(evidence)
        )
    literal_key = _comparison_key(literal)
    evidence_key = _comparison_key(evidence)
    assert literal_key is not None and evidence_key is not None
    return literal_key in evidence_key


def _material_tokens_are_supported(claim_text: str, evidence: str) -> bool:
    dates: list[date] = []
    masked_claim_parts: list[str] = []
    cursor = 0
    for match in _DATE_TOKEN.finditer(claim_text):
        parsed_date = _parse_date_match(match)
        if parsed_date is None:
            return False
        dates.append(parsed_date)
        masked_claim_parts.append(claim_text[cursor : match.start()])
        masked_claim_parts.append(" " * (match.end() - match.start()))
        cursor = match.end()
    masked_claim_parts.append(claim_text[cursor:])
    masked_claim = "".join(masked_claim_parts)
    return all(_date_is_supported(item, evidence) for item in dates) and _number_tokens(
        masked_claim
    ) <= _number_tokens(evidence)


def _parse_date_match(match: re.Match[str]) -> date | None:
    value = match.group(0).strip()
    try:
        if match.group("iso") is not None:
            return date.fromisoformat(value)
        if match.group("slash") is not None:
            return datetime.strptime(value, "%m/%d/%Y").date()
        normalized = re.sub(r"(\d{1,2})(?:st|nd|rd|th)", r"\1", value)
        normalized = normalized.replace(",", "").replace(".", "")
        for date_format in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(normalized, date_format).date()
            except ValueError:
                continue
    except ValueError:
        return None
    return None


def _date_is_supported(value: date, evidence: str) -> bool:
    month = value.strftime("%B").casefold()
    short_month = value.strftime("%b").casefold()
    year = str(value.year)
    day = str(value.day)
    normalized_evidence = evidence.casefold()
    direct_forms = {
        value.isoformat(),
        f"{value.month}/{value.day}/{value.year}",
        f"{value.month:02d}/{value.day:02d}/{value.year}",
    }
    if any(form in normalized_evidence for form in direct_forms):
        return True
    month_date = re.compile(
        rf"\b(?:{re.escape(month)}|{re.escape(short_month)}\.?)\s+0?{day}(?:st|nd|rd|th)?[,]?\s+{year}\b"
    )
    return month_date.search(normalized_evidence) is not None


def coverage_gaps(coverage: CoverageManifest) -> list[CoverageGap]:
    """Derive gaps only from trusted ingestion counts and connector manifest state."""

    gap_counts: tuple[tuple[CoverageGap, int], ...] = (
        ("processing", coverage.processing),
        ("failed", coverage.failed),
        ("unsupported", coverage.unsupported),
        ("inaccessible", coverage.inaccessible),
        ("capped", coverage.capped),
        ("unknown_branch", coverage.unknown_branches),
        ("unstable", coverage.unstable),
        ("unsafe_to_parse", coverage.unsafe_to_parse),
    )
    gaps = [reason for reason, count in gap_counts if count > 0]
    for reason in coverage.gap_reasons:
        if reason not in gaps:
            gaps.append(reason)
    if not coverage.discovery_complete and not any(
        reason in {"capped", "inaccessible", "unknown_branch"} for reason in gaps
    ):
        gaps.append("unknown_branch")
    return gaps


def _published_status(claims: Iterable[ApprovedClaim]) -> PublicationStatus:
    relations = {claim.relation for claim in claims}
    if "conflict" in relations:
        return "conflict"
    if "change" in relations:
        return "changed"
    return "evidence_supported"
