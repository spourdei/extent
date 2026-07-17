"""Fail-closed tests for the answer-publication boundary."""

from datetime import date
from uuid import UUID

from extent_api.models import CoverageManifest
from extent_api.services.publication import (
    AnswerDraft,
    ClaimDraft,
    DraftEvidenceRef,
    EvidenceBlock,
    PublicationContext,
    TextBlockOrigin,
    authorize_answer_draft,
)

WORKSPACE_ID = UUID("10000000-0000-4000-8000-000000000001")
RUN_ID = UUID("20000000-0000-4000-8000-000000000001")
OTHER_RUN_ID = UUID("20000000-0000-4000-8000-000000000002")
BLOCK_ID = UUID("30000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("40000000-0000-4000-8000-000000000001")
CLAIM_ID = UUID("50000000-0000-4000-8000-000000000001")


def _coverage(*, unsupported: int = 0) -> CoverageManifest:
    return CoverageManifest(
        capped=0,
        discovered=1 + unsupported,
        discovery_complete=True,
        failed=0,
        gap_reasons=[],
        inaccessible=0,
        processing=0,
        ready=1,
        unsafe_to_parse=0,
        unknown_branches=0,
        unstable=0,
        unsupported=unsupported,
    )


def _block(*, run_id: UUID = RUN_ID, text: str | None = None) -> EvidenceBlock:
    return EvidenceBlock(
        block_id=BLOCK_ID,
        document_version_id=DOCUMENT_ID,
        ingestion_run_id=run_id,
        normalized_text=text
        or "Project review\nEffective July 1, 2026\nApproved budget: USD 2,500\n",
        origin=TextBlockOrigin(kind="text_lines", line_start_one_based=10),
        workspace_id=WORKSPACE_ID,
    )


def _evidence(**overrides: object) -> DraftEvidenceRef:
    values: dict[str, object] = {
        "block_id": BLOCK_ID,
        "effective_date": date(2026, 7, 1),
        "entity": "Project Atlas",
        "exact_quote": "Effective July 1, 2026\nApproved budget: USD 2,500",
        "field": "approved budget",
        "scope": "project review",
        "value": "USD 2,500",
    }
    values.update(overrides)
    return DraftEvidenceRef.model_validate(values)


def _draft(
    *, text: str = "The approved budget is USD 2,500.", value: str = "USD 2,500"
) -> AnswerDraft:
    return AnswerDraft(
        claims=[
            ClaimDraft(
                claim_id=CLAIM_ID,
                evidence=[_evidence()],
                relation="fact",
                text=text,
                value=value,
            )
        ],
        summary="One supported finding.",
    )


def _context(
    *, coverage: CoverageManifest | None = None, run_terminal: bool = True
) -> PublicationContext:
    return PublicationContext(
        coverage=coverage or _coverage(),
        included_block_ids=[BLOCK_ID],
        ingestion_run_id=RUN_ID,
        run_terminal=run_terminal,
        workspace_id=WORKSPACE_ID,
    )


def test_exact_quote_publishes_with_a_resolved_line_locator() -> None:
    result = authorize_answer_draft(_draft(), blocks=[_block()], context=_context())

    assert result.status == "evidence_supported"
    assert len(result.claims) == 1
    citation = result.claims[0].citations[0]
    assert citation.locator.kind == "text_lines"
    assert citation.locator.line_start_one_based == 11
    assert citation.locator.line_end_one_based_inclusive == 12
    assert result.retrieved_passages == []


def test_matching_text_from_another_ingestion_run_is_suppressed() -> None:
    result = authorize_answer_draft(
        _draft(), blocks=[_block(run_id=OTHER_RUN_ID)], context=_context()
    )

    assert result.status == "insufficient"
    assert result.claims == []
    assert result.suppressed_claims[0].reason_codes == ["evidence_outside_authorized_run"]


def test_invented_material_value_is_suppressed_but_the_passage_remains_visible() -> None:
    result = authorize_answer_draft(
        _draft(text="The approved budget is USD 9,500.", value="USD 9,500"),
        blocks=[_block()],
        context=_context(),
    )

    assert result.status == "insufficient"
    assert result.claims == []
    assert result.suppressed_claims[0].reason_codes == [
        "claim_value_not_evidenced",
        "unsupported_claim_token",
    ]
    assert [item.exact_quote for item in result.retrieved_passages] == [_evidence().exact_quote]


def test_repeated_exact_quote_fails_closed_as_ambiguous() -> None:
    repeated = "Approved budget: USD 2,500\nApproved budget: USD 2,500\n"
    evidence = _evidence(
        effective_date=None,
        exact_quote="Approved budget: USD 2,500",
    )
    draft = _draft().model_copy(
        update={"claims": [_draft().claims[0].model_copy(update={"evidence": [evidence]})]}
    )

    result = authorize_answer_draft(draft, blocks=[_block(text=repeated)], context=_context())

    assert result.status == "insufficient"
    assert "ambiguous_exact_quote" in result.suppressed_claims[0].reason_codes


def test_nonterminal_run_never_publishes_a_material_claim() -> None:
    result = authorize_answer_draft(
        _draft(), blocks=[_block()], context=_context(run_terminal=False)
    )

    assert result.status == "coverage_limited"
    assert result.claims == []
    assert result.suppressed_claims[0].reason_codes == ["run_not_terminal"]


def test_empty_answer_distinguishes_complete_search_from_missing_coverage() -> None:
    draft = AnswerDraft(claims=[], summary="No supported finding.")

    complete = authorize_answer_draft(draft, blocks=[_block()], context=_context())
    partial = authorize_answer_draft(
        draft,
        blocks=[_block()],
        context=_context(coverage=_coverage(unsupported=1)),
    )

    assert complete.status == "insufficient"
    assert complete.coverage_gap_reasons == []
    assert partial.status == "coverage_limited"
    assert partial.coverage_gap_reasons == ["unsupported"]
