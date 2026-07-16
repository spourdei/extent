import type { components } from "../src/generated/extent-api";

export type SessionView =
  | components["schemas"]["AuthenticatedSessionView"]
  | components["schemas"]["SignedOutSessionView"];
export type IngestionStatus = components["schemas"]["WorkspaceIngestionView"]["status"];
export type SourceStatus = components["schemas"]["WorkspaceSourceView"]["status"];
export type WorkspaceSource = components["schemas"]["WorkspaceSourceView"];
export type EvidencePassage = components["schemas"]["WorkspaceEvidencePassageView"];
export type WorkspaceClaim = components["schemas"]["WorkspaceApprovedClaimView"];
export type QuestionResult = components["schemas"]["WorkspaceQuestionResultView"];
export type WorkspaceView = components["schemas"]["WorkspaceView"];
export type WorkspaceError = components["schemas"]["WorkspaceErrorView"];
