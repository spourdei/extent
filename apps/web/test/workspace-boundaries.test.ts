import assert from "node:assert/strict";
import { test } from "vitest";

import type { WorkspaceSource, WorkspaceView } from "../lib/types.ts";
import { workspaceNeedsPolling } from "../lib/workspace-polling.ts";
import { readWorkspaceError, readWorkspaceView } from "../src/parse-workspace-view.ts";

const readySource: WorkspaceSource = {
  blockCount: 2,
  driveFileId: "drive-file-1",
  errorCode: null,
  extractionMethod: "embedded_text",
  mimeType: "application/pdf",
  name: "Review.pdf",
  pageCount: 2,
  path: ["Project folder", "Review.pdf"],
  reasonCode: null,
  sizeBytes: 2_048,
  status: "ready",
};

const workspace: WorkspaceView = {
  createdAt: "2026-07-16T17:00:00Z",
  folder: { driveFolderId: "folder-id-12345", name: "Project folder" },
  history: [],
  ingestion: {
    cappedFiles: 0,
    discoveredFiles: 1,
    discoveryComplete: true,
    errorCode: null,
    failedFiles: 0,
    finishedAt: "2026-07-16T17:01:00Z",
    foldersVisited: 1,
    gapReasons: [],
    parsingFiles: 0,
    queuedFiles: 0,
    readyFiles: 1,
    runId: "10000000-0000-4000-8000-000000000001",
    startedAt: "2026-07-16T17:00:01Z",
    status: "ready",
    unsupportedFiles: 0,
  },
  sources: [readySource],
  workspaceId: "20000000-0000-4000-8000-000000000001",
};

test("accepts the complete generated workspace model", () => {
  assert.deepEqual(readWorkspaceView(workspace), workspace);
});

test("rejects malformed nested state and unexpected private fields", () => {
  assert.equal(
    readWorkspaceView({
      ...workspace,
      sources: [{ ...readySource, status: "executing" }],
    }),
    null,
  );
  assert.equal(
    readWorkspaceView({
      ...workspace,
      ingestion: { ...workspace.ingestion, readyFiles: -1 },
    }),
    null,
  );
  assert.equal(readWorkspaceView({ ...workspace, refreshToken: "must-not-cross" }), null);
});

test("accepts bounded workspace errors and rejects expanded payloads", () => {
  const valid = {
    code: "invalid_folder_url",
    message: "Paste a supported Google Drive folder link.",
    reasonCode: "unsupported_host",
  } as const;

  assert.deepEqual(readWorkspaceError(valid), valid);
  assert.equal(readWorkspaceError({ ...valid, providerPayload: "private" }), null);
  assert.equal(readWorkspaceError({ ...valid, code: "provider_error" }), null);
  assert.equal(readWorkspaceError({ ...valid, message: "x".repeat(281) }), null);
});

test("settled ready and partial workspaces stop polling", () => {
  assert.equal(workspaceNeedsPolling(workspace), false);
  assert.equal(
    workspaceNeedsPolling({
      ...workspace,
      ingestion: { ...workspace.ingestion, status: "partial" },
    }),
    false,
  );
});

test("pending counts and sources continue polling even after a ready status", () => {
  assert.equal(
    workspaceNeedsPolling({
      ...workspace,
      ingestion: { ...workspace.ingestion, queuedFiles: 1 },
    }),
    true,
  );
  assert.equal(
    workspaceNeedsPolling({
      ...workspace,
      sources: [{ ...readySource, status: "parsing" }],
    }),
    true,
  );
});

test("failed and retryable workspaces stop automatic polling", () => {
  for (const status of ["failed", "retryable"] as const) {
    assert.equal(
      workspaceNeedsPolling({
        ...workspace,
        ingestion: { ...workspace.ingestion, queuedFiles: 1, status },
        sources: [{ ...readySource, status: "queued" }],
      }),
      false,
    );
  }
});
