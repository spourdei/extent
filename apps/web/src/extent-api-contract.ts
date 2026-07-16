import type { components, paths } from "./generated/extent-api.ts";

export type ExtentApiPaths = paths;
export type SampleWorkspaceProjection = components["schemas"]["SampleWorkspaceProjection"];
export type SampleCitationContext = components["schemas"]["CitationContext"];
export type SampleWorkspaceSource = components["schemas"]["WorkspaceSource"];
export type PublishedAnswerView = components["schemas"]["PublishedAnswerView"];
export type PublishedClaim = components["schemas"]["PublishedClaim"];
export type QueryStage = components["schemas"]["QueryExecution"]["stages"][number];
export type ContextManifest = components["schemas"]["ContextManifest"];
export type NormalizedValue = components["schemas"]["MoneyValue"];
export type TerminalStatus = components["schemas"]["PublishedTerminal"]["status"];

export const queryTerminalLabel: Readonly<Record<TerminalStatus, string>> = {
  changed: "Change found",
  conflict: "Sources disagree",
  evidence_supported: "Evidence found",
  not_comparable: "Review needed",
  precedence_unknown: "Review needed",
};
