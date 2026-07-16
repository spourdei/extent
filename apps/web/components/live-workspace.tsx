"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiErrorCode, askWorkspace, getWorkspace, retryWorkspace } from "../lib/api";
import { formatFileCoverage, formatReadingProgress } from "../lib/count-copy";
import type { QuestionResult, WorkspaceView } from "../lib/types";
import {
  workspaceNeedsPolling,
  workspacePreparationIsTerminal,
} from "../lib/workspace-polling";
import { adaptQuestionResults, adaptWorkspaceSources } from "../lib/workspace-model";
import { ProductHeader } from "./product-header";
import { WorkspaceShell } from "./workspace-shell";

export function LiveWorkspace({ workspaceId }: { workspaceId: string }) {
  const [workspace, setWorkspace] = useState<WorkspaceView | null>(null);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const questionRequest = useRef<{ key: string; question: string } | null>(null);
  const errorHeadingRef = useRef<HTMLHeadingElement>(null);

  const load = useCallback(
    async (signal?: AbortSignal, preserveWorkspace = false) => {
      try {
        setWorkspace(await getWorkspace(workspaceId, signal));
        setFatalError(null);
        setRefreshError(null);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        const code = apiErrorCode(caught);
        const message =
          code === "authentication_required"
            ? "Connect the Google account that can open this workspace."
            : code === "workspace_not_found"
              ? "Extent couldn’t open this workspace with the connected account."
              : code === "request_timed_out"
                ? "The refresh took too long. The folder below is still available."
                : "Extent couldn’t refresh this workspace. Try again.";
        if (preserveWorkspace) setRefreshError(message);
        else setFatalError(message);
      }
    },
    [workspaceId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => {
      controller.abort();
    };
  }, [load]);

  useEffect(() => {
    if (fatalError) errorHeadingRef.current?.focus();
  }, [fatalError]);

  useEffect(() => {
    if (workspace === null || !workspaceNeedsPolling(workspace)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void load(controller.signal, true);
    }, 1_500);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [load, workspace]);

  const retry = async () => {
    setRetrying(true);
    setRefreshError(null);
    try {
      setWorkspace(await retryWorkspace(workspaceId));
      setRefreshError(null);
    } catch {
      setRefreshError("Extent couldn’t restart file preparation. Try again.");
    } finally {
      setRetrying(false);
    }
  };

  if (fatalError) {
    return (
      <div className="public-page">
        <ProductHeader action={<span>Workspace unavailable</span>} />
        <main className="route-state" id="main-content" role="alert">
          <div className="route-state__content">
            <div>
              <h1 ref={errorHeadingRef} tabIndex={-1}>
                Extent couldn’t open this workspace.
              </h1>
              <p>{fatalError}</p>
              <div className="intro__actions">
                <button
                  className="button button--primary"
                  onClick={() => void load()}
                  type="button"
                >
                  Try again
                </button>
                <Link className="text-link" href="/connect">
                  Back to Google Drive connection
                </Link>
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  if (workspace === null) {
    return (
      <div className="public-page">
        <ProductHeader action={<span>Opening your folder</span>} />
        <main className="route-state" id="main-content">
          <div aria-live="polite" className="route-state__content">
            <span aria-hidden="true" className="busy-dot" />
            <div>
              <h1>Opening your folder</h1>
              <p>Loading the latest file status and previous questions.</p>
            </div>
          </div>
        </main>
      </div>
    );
  }

  if (workspace.ingestion.readyFiles === 0) {
    return (
      <WorkspacePreparation
        error={refreshError}
        onRetry={() => void retry()}
        retrying={retrying}
        workspace={workspace}
      />
    );
  }

  return (
    <ConnectedWorkspace
      onRefresh={() => void load(undefined, true)}
      onAsk={async (question) => {
        if (questionRequest.current?.question !== question) {
          questionRequest.current = { key: crypto.randomUUID(), question };
        }
        const result = await askWorkspace(
          workspaceId,
          question,
          questionRequest.current.key,
        );
        questionRequest.current = null;
        return result;
      }}
      refreshError={refreshError}
      workspace={workspace}
    />
  );
}

function ConnectedWorkspace({
  onAsk,
  onRefresh,
  refreshError,
  workspace,
}: {
  onAsk: (question: string) => Promise<QuestionResult>;
  onRefresh: () => void;
  refreshError: string | null;
  workspace: WorkspaceView;
}) {
  const results = useMemo(
    () => adaptQuestionResults(workspace.history),
    [workspace.history],
  );
  const files = useMemo(
    () => adaptWorkspaceSources(workspace.sources),
    [workspace.sources],
  );
  const unavailable = Math.max(
    0,
    workspace.ingestion.discoveredFiles - workspace.ingestion.readyFiles,
  );
  return (
    <WorkspaceShell
      coverageLabel={formatFileCoverage(
        workspace.ingestion.readyFiles,
        workspace.ingestion.discoveredFiles,
        unavailable,
      )}
      evidence={results.evidence}
      files={files}
      folderTitle={workspace.folder.name ?? "Google Drive folder"}
      mode="live"
      onAsk={onAsk}
      onRefresh={onRefresh}
      questions={results.questions}
      readyFiles={workspace.ingestion.readyFiles}
      refreshError={refreshError}
      totalFiles={workspace.ingestion.discoveredFiles}
    />
  );
}

function WorkspacePreparation({
  error,
  onRetry,
  retrying,
  workspace,
}: {
  error: string | null;
  onRetry: () => void;
  retrying: boolean;
  workspace: WorkspaceView;
}) {
  const files = adaptWorkspaceSources(workspace.sources);
  const terminal = workspacePreparationIsTerminal(workspace);
  const canRetry =
    workspace.ingestion.status === "failed" || workspace.ingestion.status === "retryable";
  const title = {
    enqueue_pending: "Saving your folder",
    queued: "Folder ready to read",
    discovering: "Finding files",
    processing: "Reading your files",
    ready: "Files ready",
    partial: "Some files couldn’t be checked",
    failed: "No files are ready",
    retryable: "File preparation stopped",
  }[workspace.ingestion.status];
  return (
    <div className="public-page">
      <ProductHeader
        action={
          <span>{workspace.folder.name ?? "Connected folder"} · Drive connected</span>
        }
      />
      <main className="workspace-preparation" id="main-content">
        <section>
          <div className="preparation__intro">
            <p>Connected folder</p>
            <div className="preparation__title-row">
              {!terminal ? <span aria-hidden="true" className="busy-dot" /> : null}
              <h1>{title}</h1>
            </div>
            <p>
              {formatReadingProgress(
                workspace.ingestion.discoveredFiles,
                workspace.ingestion.readyFiles,
                workspace.ingestion.parsingFiles + workspace.ingestion.queuedFiles,
              )}
            </p>
          </div>
          <div className="file-progress-list" aria-busy={!terminal}>
            {files.length === 0 ? (
              <p className="empty-row">Files will appear here as Extent finds them.</p>
            ) : (
              files.map((file, index) => (
                <div
                  className="file-progress-row"
                  key={file.id ?? `${file.folder}:${file.name}:${String(index)}`}
                >
                  <span aria-hidden="true" className={`file-dot file-dot--${file.tone}`} />
                  <span className="file-progress-row__name">
                    {file.name}
                    <span> · {file.folder}</span>
                  </span>
                  <span className={`file-state file-state--${file.tone}`}>
                    {file.state}
                  </span>
                </div>
              ))
            )}
          </div>
          {terminal ? (
            <div className="preparation__actions">
              {canRetry ? (
                <button
                  className="button button--primary"
                  disabled={retrying}
                  onClick={onRetry}
                  type="button"
                >
                  {retrying ? "Trying again…" : "Try reading the folder again"}
                </button>
              ) : (
                <p>No readable files are available in this folder.</p>
              )}
              <Link className="text-link" href="/connect">
                Choose another folder
              </Link>
            </div>
          ) : null}
          {error ? (
            <p className="field-error" role="alert">
              {error}
            </p>
          ) : null}
        </section>
      </main>
    </div>
  );
}
