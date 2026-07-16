import type { components } from "./generated/extent-api.ts";
import { readQuestionResult } from "./parse-workspace-question-result.ts";

export type WorkspaceView = components["schemas"]["WorkspaceView"];
export type WorkspaceErrorView = components["schemas"]["WorkspaceErrorView"];

type WorkspaceIngestionView = WorkspaceView["ingestion"];
type WorkspaceSourceView = WorkspaceView["sources"][number];

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export function readWorkspaceView(value: unknown): WorkspaceView | null {
  return isWorkspaceView(value) ? value : null;
}

export function readWorkspaceError(value: unknown): WorkspaceErrorView | null {
  return isWorkspaceError(value) ? value : null;
}

function isWorkspaceView(value: unknown): value is WorkspaceView {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "createdAt",
      "folder",
      "history",
      "ingestion",
      "sources",
      "workspaceId",
    ]) &&
    isUuid(value.workspaceId) &&
    isAwareDateTime(value.createdAt) &&
    isRecord(value.folder) &&
    hasExactKeys(value.folder, ["driveFolderId", "name"]) &&
    isBoundedString(value.folder.driveFolderId, 10, 200) &&
    isNullableBoundedString(value.folder.name, 1, 1_024) &&
    Array.isArray(value.history) &&
    value.history.length <= 20 &&
    value.history.every((result) => readQuestionResult(result) !== null) &&
    isIngestion(value.ingestion) &&
    Array.isArray(value.sources) &&
    value.sources.length <= 500 &&
    value.sources.every(isSource)
  );
}

function isIngestion(value: unknown): value is WorkspaceIngestionView {
  if (!isRecord(value)) return false;
  return (
    hasExactKeys(value, [
      "cappedFiles",
      "discoveredFiles",
      "discoveryComplete",
      "errorCode",
      "failedFiles",
      "finishedAt",
      "foldersVisited",
      "gapReasons",
      "parsingFiles",
      "queuedFiles",
      "readyFiles",
      "runId",
      "startedAt",
      "status",
      "unsupportedFiles",
    ]) &&
    isNonnegativeInteger(value.cappedFiles) &&
    isNonnegativeInteger(value.discoveredFiles) &&
    typeof value.discoveryComplete === "boolean" &&
    isNullableBoundedString(value.errorCode, 1, 80) &&
    isNonnegativeInteger(value.failedFiles) &&
    isNullableAwareDateTime(value.finishedAt) &&
    isNonnegativeInteger(value.foldersVisited) &&
    Array.isArray(value.gapReasons) &&
    value.gapReasons.length <= 8 &&
    value.gapReasons.every(isGapReason) &&
    isNonnegativeInteger(value.parsingFiles) &&
    isNonnegativeInteger(value.queuedFiles) &&
    isNonnegativeInteger(value.readyFiles) &&
    isUuid(value.runId) &&
    isNullableAwareDateTime(value.startedAt) &&
    isIngestionStatus(value.status) &&
    isNonnegativeInteger(value.unsupportedFiles)
  );
}

function isSource(value: unknown): value is WorkspaceSourceView {
  if (!isRecord(value)) return false;
  return (
    hasExactKeys(value, [
      "blockCount",
      "driveFileId",
      "errorCode",
      "extractionMethod",
      "mimeType",
      "name",
      "pageCount",
      "path",
      "reasonCode",
      "sizeBytes",
      "status",
    ]) &&
    isNonnegativeInteger(value.blockCount) &&
    isBoundedString(value.driveFileId, 1, 200) &&
    isNullableBoundedString(value.errorCode, 1, 80) &&
    isExtractionMethod(value.extractionMethod) &&
    isBoundedString(value.mimeType, 1, 255) &&
    isBoundedString(value.name, 1, 1_024) &&
    isNullableNonnegativeInteger(value.pageCount) &&
    Array.isArray(value.path) &&
    value.path.length >= 2 &&
    value.path.length <= 8 &&
    value.path.every((part) => isBoundedString(part, 1, 1_024)) &&
    isNullableBoundedString(value.reasonCode, 1, 80) &&
    isNullableNonnegativeInteger(value.sizeBytes) &&
    isSourceStatus(value.status)
  );
}

function isExtractionMethod(
  value: unknown,
): value is WorkspaceSourceView["extractionMethod"] {
  return value === null || value === "embedded_text" || value === "ocr";
}

function isWorkspaceError(value: unknown): value is WorkspaceErrorView {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  return (
    keys.every((key) => key === "code" || key === "message" || key === "reasonCode") &&
    Object.hasOwn(value, "code") &&
    Object.hasOwn(value, "message") &&
    isWorkspaceErrorCode(value.code) &&
    isBoundedString(value.message, 1, 280) &&
    (!Object.hasOwn(value, "reasonCode") ||
      isNullableBoundedString(value.reasonCode, 1, 80))
  );
}

function isIngestionStatus(value: unknown): value is WorkspaceIngestionView["status"] {
  return (
    value === "enqueue_pending" ||
    value === "queued" ||
    value === "discovering" ||
    value === "processing" ||
    value === "ready" ||
    value === "partial" ||
    value === "failed" ||
    value === "retryable"
  );
}

function isSourceStatus(value: unknown): value is WorkspaceSourceView["status"] {
  return (
    value === "queued" ||
    value === "parsing" ||
    value === "ready" ||
    value === "failed" ||
    value === "unsupported" ||
    value === "capped"
  );
}

function isGapReason(
  value: unknown,
): value is WorkspaceIngestionView["gapReasons"][number] {
  return (
    value === "processing" ||
    value === "failed" ||
    value === "unsupported" ||
    value === "inaccessible" ||
    value === "capped" ||
    value === "unknown_branch" ||
    value === "unstable" ||
    value === "unsafe_to_parse"
  );
}

function isWorkspaceErrorCode(value: unknown): value is WorkspaceErrorView["code"] {
  return (
    value === "authentication_required" ||
    value === "idempotency_conflict" ||
    value === "invalid_folder_url" ||
    value === "origin_rejected" ||
    value === "rate_limit_unavailable" ||
    value === "rate_limited" ||
    value === "retrieval_unavailable" ||
    value === "workspace_not_retryable" ||
    value === "workspace_not_ready" ||
    value === "workspace_not_found"
  );
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).every((key) => keys.includes(key)) &&
    keys.every((key) => Object.hasOwn(value, key))
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBoundedString(
  value: unknown,
  minimum: number,
  maximum: number,
): value is string {
  return typeof value === "string" && value.length >= minimum && value.length <= maximum;
}

function isNullableBoundedString(
  value: unknown,
  minimum: number,
  maximum: number,
): value is string | null {
  return value === null || isBoundedString(value, minimum, maximum);
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isNullableNonnegativeInteger(value: unknown): value is number | null {
  return value === null || isNonnegativeInteger(value);
}

function isAwareDateTime(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /(?:Z|[+-]\d{2}:\d{2})$/u.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isNullableAwareDateTime(value: unknown): value is string | null {
  return value === null || isAwareDateTime(value);
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && uuidPattern.test(value);
}
