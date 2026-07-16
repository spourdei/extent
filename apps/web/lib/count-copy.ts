export function formatCount(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${String(count)} ${count === 1 ? singular : plural}`;
}

export function formatFileCoverage(
  readyFiles: number,
  totalFiles: number,
  unavailableFiles: number,
): string {
  const unavailableCopy =
    unavailableFiles > 0 ? ` · ${formatCount(unavailableFiles, "file")} not checked` : "";
  return `${String(readyFiles)} of ${formatCount(totalFiles, "file")} ready${unavailableCopy}`;
}

export function formatDiscoverySummary(
  discoveredFiles: number,
  foldersVisited: number,
  readyFiles: number,
  unavailableFiles: number,
): string {
  const unavailableCopy =
    unavailableFiles > 0 ? ` · ${formatCount(unavailableFiles, "file")} unavailable` : "";
  return `${formatCount(discoveredFiles, "file")} found across ${formatCount(foldersVisited, "folder")} · ${formatCount(readyFiles, "file")} ready${unavailableCopy}`;
}

export function formatReadingProgress(
  discoveredFiles: number,
  readyFiles: number,
  pendingFiles: number,
): string {
  return `${formatCount(discoveredFiles, "file")} found · ${formatCount(readyFiles, "file")} ready · ${formatCount(pendingFiles, "file")} still being read`;
}

export function formatCoverageSummary(
  totalFiles: number,
  readyFiles: number,
  unavailableFiles: number,
): string {
  return `${formatCount(totalFiles, "file")} found · ${formatCount(readyFiles, "file")} ready · ${formatCount(unavailableFiles, "file")} unavailable`;
}
