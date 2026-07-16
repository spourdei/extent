import type { WorkspaceView } from "./types";

const terminalStatuses = new Set<WorkspaceView["ingestion"]["status"]>([
  "ready",
  "partial",
  "failed",
  "retryable",
]);

export function workspaceNeedsPolling(workspace: WorkspaceView): boolean {
  if (
    workspace.ingestion.status === "failed" ||
    workspace.ingestion.status === "retryable"
  ) {
    return false;
  }
  const pendingCount = workspace.ingestion.queuedFiles + workspace.ingestion.parsingFiles;
  const hasPendingSource = workspace.sources.some(
    (source) => source.status === "queued" || source.status === "parsing",
  );
  return (
    pendingCount > 0 ||
    hasPendingSource ||
    !terminalStatuses.has(workspace.ingestion.status)
  );
}

export function workspacePreparationIsTerminal(workspace: WorkspaceView): boolean {
  return !workspaceNeedsPolling(workspace);
}
