"""Frozen, deterministic evaluation of the deployed publication authority."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from extent_api.models import CoverageGap, CoverageManifest
from extent_api.services.publication import (
    AnswerDraft,
    EvidenceBlock,
    PdfBlockOrigin,
    PolicyNote,
    PublicationContext,
    PublicationResult,
    Relation,
    ResolvedPdfLocator,
    ResolvedTextLocator,
    SuppressionReason,
    TextBlockOrigin,
    authorize_answer_draft,
)


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FrozenFixture(EvaluationModel):
    block_id: UUID
    document_version_id: UUID
    fixture_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$", max_length=80)]
    ingestion_run_id: UUID
    origin: PdfBlockOrigin | TextBlockOrigin
    text: Annotated[str, Field(min_length=1, max_length=50_000)]
    workspace_id: UUID


class EvaluationObservation(EvaluationModel):
    approved_relations: Annotated[list[Relation], Field(max_length=3)] = Field(
        default_factory=list
    )
    citation_locators: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=80)]], Field(max_length=6)
    ] = Field(default_factory=list)
    coverage_gap_reasons: Annotated[list[CoverageGap], Field(max_length=8)] = Field(
        default_factory=list
    )
    policy_notes: Annotated[list[PolicyNote], Field(max_length=9)] = Field(default_factory=list)
    status: Literal[
        "evidence_supported",
        "changed",
        "conflict",
        "insufficient",
        "coverage_limited",
    ]
    suppression_reasons: Annotated[list[SuppressionReason], Field(max_length=24)] = Field(
        default_factory=list
    )


class FrozenEvaluationCase(EvaluationModel):
    available_fixture_ids: Annotated[list[str], Field(min_length=1, max_length=6)]
    case_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$", max_length=80)]
    coverage: CoverageManifest | None = None
    draft: AnswerDraft
    expected: EvaluationObservation
    question: Annotated[str, Field(min_length=1, max_length=500)]
    retrieved_fixture_ids: Annotated[list[str], Field(max_length=6)] | None = None
    run_terminal: bool = True

    @model_validator(mode="after")
    def retrieved_fixtures_are_available(self) -> Self:
        retrieved = self.retrieved_fixture_ids or self.available_fixture_ids
        if not set(retrieved) <= set(self.available_fixture_ids):
            raise ValueError("retrieved fixtures must be available to the case")
        if len(set(self.available_fixture_ids)) != len(self.available_fixture_ids):
            raise ValueError("available fixture ids must be unique")
        if len(set(retrieved)) != len(retrieved):
            raise ValueError("retrieved fixture ids must be unique")
        return self


class FrozenEvaluationManifest(EvaluationModel):
    cases: Annotated[list[FrozenEvaluationCase], Field(min_length=1, max_length=50)]
    fixtures: Annotated[list[FrozenFixture], Field(min_length=1, max_length=50)]
    ingestion_run_id: UUID
    manifest_version: Literal["extent-frozen-eval-v1"]
    workspace_id: UUID

    @model_validator(mode="after")
    def identities_and_fixture_coverage_are_complete(self) -> Self:
        fixture_ids = [fixture.fixture_id for fixture in self.fixtures]
        block_ids = [fixture.block_id for fixture in self.fixtures]
        case_ids = [case.case_id for case in self.cases]
        if len(set(fixture_ids)) != len(fixture_ids):
            raise ValueError("fixture ids must be unique")
        if len(set(block_ids)) != len(block_ids):
            raise ValueError("fixture block ids must be unique")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case ids must be unique")
        known = set(fixture_ids)
        referenced = {
            fixture_id for case in self.cases for fixture_id in case.available_fixture_ids
        }
        unknown = referenced - known
        if unknown:
            raise ValueError(f"cases reference unknown fixtures: {sorted(unknown)!r}")
        unused = known - referenced
        if unused:
            raise ValueError(f"fixtures are not covered by any case: {sorted(unused)!r}")
        return self


class EvaluationCaseResult(EvaluationModel):
    actual: EvaluationObservation
    case_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$", max_length=80)]
    passed: bool


class FrozenEvaluationReport(EvaluationModel):
    cases: list[EvaluationCaseResult]
    failed_case_ids: list[str]
    failed_cases: int
    manifest_version: Literal["extent-frozen-eval-v1"]
    passed_cases: int
    policy_version: Literal["publication-policy-v1"]
    total_cases: int


def load_frozen_manifest(path: Path) -> FrozenEvaluationManifest:
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError("frozen evaluation manifest exceeds 1 MB")
    return FrozenEvaluationManifest.model_validate_json(raw)


def run_frozen_evaluation(manifest: FrozenEvaluationManifest) -> FrozenEvaluationReport:
    fixtures = {fixture.fixture_id: fixture for fixture in manifest.fixtures}
    case_results: list[EvaluationCaseResult] = []
    for case in manifest.cases:
        blocks = [
            _evidence_block(fixtures[fixture_id]) for fixture_id in case.available_fixture_ids
        ]
        publication = authorize_answer_draft(
            case.draft,
            blocks=blocks,
            context=PublicationContext(
                coverage=case.coverage or _complete_coverage(len(blocks)),
                included_block_ids=[
                    fixtures[fixture_id].block_id
                    for fixture_id in (case.retrieved_fixture_ids or case.available_fixture_ids)
                ],
                ingestion_run_id=manifest.ingestion_run_id,
                run_terminal=case.run_terminal,
                workspace_id=manifest.workspace_id,
            ),
        )
        actual = _observation(publication)
        case_results.append(
            EvaluationCaseResult(
                actual=actual,
                case_id=case.case_id,
                passed=actual == case.expected,
            )
        )
    failed_case_ids = [result.case_id for result in case_results if not result.passed]
    return FrozenEvaluationReport(
        cases=case_results,
        failed_case_ids=failed_case_ids,
        failed_cases=len(failed_case_ids),
        manifest_version=manifest.manifest_version,
        passed_cases=len(case_results) - len(failed_case_ids),
        policy_version="publication-policy-v1",
        total_cases=len(case_results),
    )


def _evidence_block(fixture: FrozenFixture) -> EvidenceBlock:
    return EvidenceBlock(
        block_id=fixture.block_id,
        document_version_id=fixture.document_version_id,
        ingestion_run_id=fixture.ingestion_run_id,
        normalized_text=fixture.text,
        origin=fixture.origin,
        workspace_id=fixture.workspace_id,
    )


def _complete_coverage(ready: int) -> CoverageManifest:
    return CoverageManifest(
        capped=0,
        discovered=ready,
        discovery_complete=True,
        failed=0,
        gap_reasons=[],
        inaccessible=0,
        processing=0,
        ready=ready,
        unsafe_to_parse=0,
        unknown_branches=0,
        unstable=0,
        unsupported=0,
    )


def _observation(publication: PublicationResult) -> EvaluationObservation:
    return EvaluationObservation(
        approved_relations=[claim.relation for claim in publication.claims],
        citation_locators=[
            _locator_key(citation.locator)
            for claim in publication.claims
            for citation in claim.citations
        ],
        coverage_gap_reasons=list(publication.coverage_gap_reasons),
        policy_notes=sorted(
            note for claim in publication.claims for note in claim.policy_notes
        ),
        status=publication.status,
        suppression_reasons=sorted(
            reason for claim in publication.suppressed_claims for reason in claim.reason_codes
        ),
    )


def _locator_key(locator: ResolvedPdfLocator | ResolvedTextLocator) -> str:
    start = locator.normalized_start_in_block
    end = locator.normalized_end_exclusive_in_block
    if isinstance(locator, ResolvedPdfLocator):
        return f"pdf:{locator.page_index_zero_based}:{start}-{end}"
    return (
        f"lines:{locator.line_start_one_based}-"
        f"{locator.line_end_one_based_inclusive}:{start}-{end}"
    )
