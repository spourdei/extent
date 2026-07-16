import type { components } from "./generated/extent-api.ts";

type QuestionResult = components["schemas"]["WorkspaceQuestionResultView"];
type EvidencePassage = components["schemas"]["WorkspaceEvidencePassageView"];
type ApprovedClaim = components["schemas"]["WorkspaceApprovedClaimView"];
type CoverageGap = QuestionResult["coverageGapReasons"][number];

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export function readQuestionResult(value: unknown): QuestionResult | null {
  return isQuestionResult(value) ? value : null;
}

function isQuestionResult(value: unknown): value is QuestionResult {
  if (!isRecord(value)) return false;
  return (
    hasExactKeys(value, [
      "answerId",
      "claims",
      "coverageGapReasons",
      "createdAt",
      "generationStatus",
      "message",
      "passages",
      "policyVersion",
      "question",
      "questionId",
      "status",
    ]) &&
    isUuid(value.answerId) &&
    isUuid(value.questionId) &&
    typeof value.question === "string" &&
    value.question.length >= 3 &&
    value.question.length <= 2_000 &&
    typeof value.message === "string" &&
    value.message.length >= 1 &&
    value.message.length <= 280 &&
    isAwareDateTime(value.createdAt) &&
    isResultStatus(value.status) &&
    isGenerationStatus(value.generationStatus) &&
    isPolicyVersion(value.policyVersion) &&
    Array.isArray(value.claims) &&
    value.claims.length <= (isCompleteDataPolicy(value.policyVersion) ? 200 : 3) &&
    value.claims.every(isApprovedClaim) &&
    Array.isArray(value.passages) &&
    value.passages.length <= 6 &&
    value.passages.every(isEvidencePassage) &&
    Array.isArray(value.coverageGapReasons) &&
    value.coverageGapReasons.length <= 8 &&
    value.coverageGapReasons.every(isCoverageGap) &&
    resultMatchesPolicy(value)
  );
}

function isApprovedClaim(value: unknown): value is ApprovedClaim {
  if (!isRecord(value)) return false;
  return (
    hasExactKeys(value, ["citations", "claimId", "relation", "text", "value"]) &&
    isUuid(value.claimId) &&
    typeof value.text === "string" &&
    value.text.length > 0 &&
    value.text.length <= 800 &&
    (value.value === null ||
      (typeof value.value === "string" &&
        value.value.length > 0 &&
        value.value.length <= 120)) &&
    isClaimRelation(value.relation) &&
    Array.isArray(value.citations) &&
    value.citations.length >= 1 &&
    value.citations.length <= 2 &&
    value.citations.every(isEvidencePassage)
  );
}

function isEvidencePassage(value: unknown): value is EvidencePassage {
  if (!isRecord(value)) return false;
  const common =
    hasExactKeys(value, [
      "blockId",
      "driveFileId",
      "endExclusiveInBlock",
      "exactQuote",
      "lineStartOneBased",
      "normalizedValue",
      "originKind",
      "pageIndexZeroBased",
      "path",
      "printedPageLabel",
      "rawValue",
      "role",
      "sourceName",
      "startInBlock",
    ]) &&
    isUuid(value.blockId) &&
    typeof value.driveFileId === "string" &&
    /^[A-Za-z0-9_-]{1,200}$/.test(value.driveFileId) &&
    isIntegerAtLeast(value.startInBlock, 0) &&
    isIntegerAtLeast(value.endExclusiveInBlock, 1) &&
    value.endExclusiveInBlock > value.startInBlock &&
    typeof value.exactQuote === "string" &&
    value.exactQuote.length > 0 &&
    value.exactQuote.length <= 2_000 &&
    isEvidenceRole(value.role) &&
    isComparisonValuePair(value.rawValue, value.normalizedValue) &&
    typeof value.sourceName === "string" &&
    value.sourceName.length > 0 &&
    value.sourceName.length <= 1_024 &&
    Array.isArray(value.path) &&
    value.path.length >= 2 &&
    value.path.length <= 8 &&
    value.path.every(
      (part) => typeof part === "string" && part.length > 0 && part.length <= 1_024,
    );
  if (!common) return false;
  if (value.originKind === "pdf_page") {
    return (
      isIntegerAtLeast(value.pageIndexZeroBased, 0) &&
      value.lineStartOneBased === null &&
      (value.printedPageLabel === null ||
        (typeof value.printedPageLabel === "string" &&
          value.printedPageLabel.length >= 1 &&
          value.printedPageLabel.length <= 40))
    );
  }
  if (value.originKind === "text_lines") {
    return (
      isIntegerAtLeast(value.lineStartOneBased, 1) &&
      value.pageIndexZeroBased === null &&
      value.printedPageLabel === null
    );
  }
  return false;
}

function isResultStatus(value: unknown): value is QuestionResult["status"] {
  return (
    value === "changed" ||
    value === "conflict" ||
    value === "coverage_limited" ||
    value === "evidence_retrieved" ||
    value === "evidence_supported" ||
    value === "insufficient"
  );
}

function isGenerationStatus(value: unknown): value is QuestionResult["generationStatus"] {
  return value === "completed" || value === "failed" || value === "not_configured";
}

function isPolicyVersion(value: unknown): value is QuestionResult["policyVersion"] {
  return (
    value === "exhaustive-extraction-policy-v1" ||
    value === "exhaustive-premium-policy-v1" ||
    value === "clarification-policy-v1" ||
    value === "publication-policy-v1" ||
    value === "retrieval-policy-v1" ||
    value === "source-state-policy-v1" ||
    value === "structured-analysis-policy-v1"
  );
}

function resultMatchesPolicy(value: Record<string, unknown>): boolean {
  if (value.policyVersion === "clarification-policy-v1") {
    return (
      value.generationStatus === "completed" &&
      value.status === "insufficient" &&
      Array.isArray(value.claims) &&
      value.claims.length === 0
    );
  }
  if (value.policyVersion === "source-state-policy-v1") {
    return (
      value.generationStatus === "completed" &&
      value.status === "insufficient" &&
      Array.isArray(value.claims) &&
      value.claims.length === 0 &&
      Array.isArray(value.passages) &&
      value.passages.length === 0
    );
  }
  if (!isCompleteDataPolicy(value.policyVersion)) return true;
  const claims = Array.isArray(value.claims) ? value.claims : [];
  return (
    value.generationStatus === "completed" &&
    (value.status === "coverage_limited" ||
      value.status === "evidence_supported" ||
      value.status === "insufficient") &&
    Array.isArray(value.passages) &&
    value.passages.length === 0 &&
    Array.isArray(value.claims) &&
    claims.every(
      (claim) =>
        isRecord(claim) && claim.relation === "fact" && typeof claim.value === "string",
    ) &&
    (value.status !== "evidence_supported" || claims.length > 0) &&
    (value.status !== "insufficient" || claims.length === 0)
  );
}

function isExhaustiveExtractionPolicy(value: unknown): boolean {
  return (
    value === "exhaustive-extraction-policy-v1" || value === "exhaustive-premium-policy-v1"
  );
}

function isCompleteDataPolicy(value: unknown): boolean {
  return isExhaustiveExtractionPolicy(value) || value === "structured-analysis-policy-v1";
}

function isCoverageGap(value: unknown): value is CoverageGap {
  return (
    value === "capped" ||
    value === "failed" ||
    value === "inaccessible" ||
    value === "processing" ||
    value === "unknown_branch" ||
    value === "unsafe_to_parse" ||
    value === "unstable" ||
    value === "unsupported"
  );
}

function isClaimRelation(value: unknown): value is ApprovedClaim["relation"] {
  return (
    value === "change" || value === "conflict" || value === "fact" || value === "unclear"
  );
}

function isEvidenceRole(value: unknown): value is EvidencePassage["role"] {
  return (
    value === null ||
    value === "support" ||
    value === "before" ||
    value === "after" ||
    value === "left" ||
    value === "right"
  );
}

function isComparisonValuePair(rawValue: unknown, normalizedValue: unknown): boolean {
  if (rawValue === null || normalizedValue === null) {
    return rawValue === null && normalizedValue === null;
  }
  return (
    typeof rawValue === "string" &&
    rawValue.length >= 1 &&
    rawValue.length <= 120 &&
    typeof normalizedValue === "string" &&
    normalizedValue.length >= 1 &&
    normalizedValue.length <= 120
  );
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && uuidPattern.test(value);
}

function isAwareDateTime(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /(?:Z|[+-]\d{2}:\d{2})$/u.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isIntegerAtLeast(value: unknown, minimum: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).every((key) => keys.includes(key)) &&
    keys.every((key) => Object.hasOwn(value, key))
  );
}
