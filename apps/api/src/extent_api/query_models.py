"""Public contracts for bounded answers and exhaustive extraction results."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from extent_api.models import ApiModel, CoverageGap

EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT = 200
CLARIFICATION_POLICY_VERSION = "clarification-policy-v1"
SOURCE_STATE_POLICY_VERSION = "source-state-policy-v1"
COMPLETE_DATA_POLICIES = frozenset(
    {
        "exhaustive-extraction-policy-v1",
        "exhaustive-premium-policy-v1",
        "structured-analysis-policy-v1",
    }
)


class AskWorkspaceQuestionRequest(ApiModel):
    question: Annotated[str, Field(min_length=3, max_length=2_000)]

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("question must contain at least three non-whitespace characters")
        return normalized


class WorkspaceEvidencePassageView(ApiModel):
    block_id: UUID
    drive_file_id: Annotated[
        str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    ]
    end_exclusive_in_block: Annotated[int, Field(gt=0)]
    exact_quote: Annotated[str, Field(min_length=1, max_length=2_000)]
    line_start_one_based: Annotated[int, Field(gt=0)] | None
    normalized_value: Annotated[str, Field(min_length=1, max_length=120)] | None
    origin_kind: Literal["pdf_page", "text_lines"]
    page_index_zero_based: Annotated[int, Field(ge=0)] | None
    path: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=1_024)]],
        Field(min_length=2, max_length=8),
    ]
    printed_page_label: Annotated[str, Field(min_length=1, max_length=40)] | None
    raw_value: Annotated[str, Field(min_length=1, max_length=120)] | None
    role: Literal["support", "before", "after", "left", "right"] | None
    source_name: Annotated[str, Field(min_length=1, max_length=1_024)]
    start_in_block: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def locator_matches_origin(self) -> Self:
        if self.origin_kind == "pdf_page" and (
            self.page_index_zero_based is None or self.line_start_one_based is not None
        ):
            raise ValueError("PDF passages require only a page locator")
        if self.origin_kind == "text_lines" and (
            self.line_start_one_based is None
            or self.page_index_zero_based is not None
            or self.printed_page_label is not None
        ):
            raise ValueError("text passages require only a line locator")
        if (self.raw_value is None) != (self.normalized_value is None):
            raise ValueError("raw and normalized values must be present together")
        if self.end_exclusive_in_block <= self.start_in_block:
            raise ValueError("evidence passages require a non-empty source span")
        return self


class WorkspaceApprovedClaimView(ApiModel):
    citations: Annotated[list[WorkspaceEvidencePassageView], Field(min_length=1, max_length=2)]
    claim_id: UUID
    relation: Literal["fact", "change", "conflict", "unclear"]
    text: Annotated[str, Field(min_length=1, max_length=800)]
    value: Annotated[str, Field(min_length=1, max_length=120)] | None


class WorkspaceQuestionResultView(ApiModel):
    answer_id: UUID
    claims: Annotated[
        list[WorkspaceApprovedClaimView],
        Field(max_length=EXHAUSTIVE_EXTRACTION_CLAIM_LIMIT),
    ]
    coverage_gap_reasons: Annotated[list[CoverageGap], Field(max_length=8)]
    created_at: AwareDatetime
    generation_status: Literal["not_configured", "failed", "completed"]
    message: Annotated[str, Field(min_length=1, max_length=280)]
    passages: Annotated[list[WorkspaceEvidencePassageView], Field(max_length=6)]
    policy_version: Literal[
        "retrieval-policy-v1",
        "publication-policy-v1",
        "clarification-policy-v1",
        "exhaustive-extraction-policy-v1",
        "exhaustive-premium-policy-v1",
        "source-state-policy-v1",
        "structured-analysis-policy-v1",
    ]
    question: Annotated[str, Field(min_length=3, max_length=2_000)]
    question_id: UUID
    status: Literal[
        "evidence_retrieved",
        "evidence_supported",
        "changed",
        "conflict",
        "insufficient",
        "coverage_limited",
    ]

    @model_validator(mode="after")
    def claims_match_policy(self) -> Self:
        if self.policy_version == CLARIFICATION_POLICY_VERSION:
            if self.generation_status != "completed":
                raise ValueError("clarification results must be completed")
            if self.status != "insufficient" or self.claims:
                raise ValueError("clarification results cannot publish claims")
            return self
        if self.policy_version == SOURCE_STATE_POLICY_VERSION:
            if self.generation_status != "completed":
                raise ValueError("source-state results must be completed")
            if self.status != "insufficient" or self.claims or self.passages:
                raise ValueError("source-state results only report trusted manifest state")
            return self
        if self.policy_version in COMPLETE_DATA_POLICIES:
            if self.generation_status != "completed":
                raise ValueError("complete-data results must be completed")
            if self.passages:
                raise ValueError("complete-data results store evidence on each claim")
            if self.status not in {
                "evidence_supported",
                "coverage_limited",
                "insufficient",
            }:
                raise ValueError("complete-data result has an invalid status")
            if any(claim.relation != "fact" or claim.value is None for claim in self.claims):
                raise ValueError("complete-data results require valued fact claims")
            if self.status == "evidence_supported" and not self.claims:
                raise ValueError("supported complete-data result requires at least one value")
            if self.status == "insufficient" and self.claims:
                raise ValueError("insufficient complete-data result cannot contain values")
            return self
        if len(self.claims) > 3:
            raise ValueError("bounded publication results may contain at most three claims")
        return self
