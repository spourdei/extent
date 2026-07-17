"use client";

import Link from "next/link";
import { type SyntheticEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  apiErrorCode,
  createWorkspace,
  disconnectSession,
  getSession,
  getWorkspace,
  retryWorkspace,
} from "../lib/api";
import { formatCount, formatDiscoverySummary } from "../lib/count-copy";
import type { SessionView, WorkspaceView } from "../lib/types";
import {
  workspaceNeedsPolling,
  workspacePreparationIsTerminal,
} from "../lib/workspace-polling";
import { adaptWorkspaceSources } from "../lib/workspace-model";
import { ProductHeader } from "./product-header";

type ConnectPhase = "checking" | "connect" | "folder" | "prepare";
type FormSubmitEvent = SyntheticEvent<HTMLFormElement, SubmitEvent>;

const authCopy: Readonly<Record<string, string>> = {
  access_denied:
    "This Google account declined access, or your organization blocks it. Connect a different account, or ask your Workspace admin.",
  configuration_unavailable:
    "Google Drive isn’t configured for this environment. Try the prepared sample instead.",
  invalid_state:
    "That sign-in link expired or was already used. Start the connection again.",
  oauth_failed:
    "Google couldn’t complete the sign-in, so nothing was connected. Trying again is safe.",
};

const folderErrorCopy: Readonly<Record<string, string>> = {
  authentication_required:
    "Connect the Google account that can open this folder, then try again.",
  idempotency_conflict:
    "This folder request changed while it was being retried. Check the link and try again.",
  invalid_folder_url:
    "Paste a Google Drive folder link, such as https://drive.google.com/drive/folders/…",
  origin_rejected: "Refresh this page before checking the folder again.",
  rate_limit_unavailable:
    "Extent couldn’t check the request limit. Wait a moment, then try again.",
  rate_limited:
    "Too many folder requests were made in a short time. Wait a moment, then try again.",
  retrieval_unavailable:
    "Extent couldn’t check this folder. Your link is still here, so you can try again.",
  request_timed_out:
    "The folder check took too long. Your link is still here, so retrying is safe.",
  workspace_not_found:
    "Extent couldn’t open this folder with the connected account. Check the link and Drive access, then try again.",
};

function phaseForSession(session: SessionView): ConnectPhase {
  return session.status === "authenticated" ? "folder" : "connect";
}

export function ConnectFlow({
  initialAuthResult,
  initialReferenceId,
}: {
  initialAuthResult: string | null;
  initialReferenceId: string | null;
}) {
  const [phase, setPhase] = useState<ConnectPhase>("checking");
  const [session, setSession] = useState<SessionView | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [wasDisconnected, setWasDisconnected] = useState(false);
  const [folderUrl, setFolderUrl] = useState("");
  const [folderError, setFolderError] = useState<string | null>(null);
  const [folderSubmitting, setFolderSubmitting] = useState(false);
  const [workspace, setWorkspace] = useState<WorkspaceView | null>(null);
  const [retrying, setRetrying] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  const loadSession = useCallback(async (signal?: AbortSignal) => {
    setConnectionError(null);
    setPhase("checking");
    try {
      const nextSession = await getSession(signal);
      setSession(nextSession);
      setPhase(phaseForSession(nextSession));
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setConnectionError(
        "Extent couldn’t confirm whether Google Drive is connected. Try again before choosing a folder.",
      );
      setPhase("connect");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadSession(controller.signal);
    return () => {
      controller.abort();
    };
  }, [loadSession]);

  useEffect(() => {
    if (phase !== "prepare" || workspace === null || !workspaceNeedsPolling(workspace)) {
      return;
    }
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const refreshed = await getWorkspace(workspace.workspaceId, controller.signal);
        setWorkspace(refreshed);
        setFolderError(null);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setFolderError("Extent couldn’t refresh file preparation. Try again.");
        }
      }
    };
    const timer = window.setTimeout(() => {
      void refresh();
    }, 1_500);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [phase, workspace]);

  const disconnect = async () => {
    setDisconnecting(true);
    setConnectionError(null);
    try {
      await disconnectSession();
      setSession({ googleOauthAvailable: true, status: "signed_out" });
      setPhase("connect");
      setWasDisconnected(true);
      window.history.replaceState(null, "", "/connect");
    } catch {
      setConnectionError("Extent couldn’t remove Google access. Try again.");
    } finally {
      setDisconnecting(false);
    }
  };

  const submitFolder = async (event: FormSubmitEvent) => {
    event.preventDefault();
    if (folderSubmitting || folderUrl.trim().length === 0) return;
    setFolderSubmitting(true);
    setFolderError(null);
    idempotencyKey.current ??= crypto.randomUUID();
    try {
      const nextWorkspace = await createWorkspace(folderUrl.trim(), idempotencyKey.current);
      setWorkspace(nextWorkspace);
      setPhase("prepare");
    } catch (error) {
      const code = apiErrorCode(error);
      setFolderError(
        (code ? folderErrorCopy[code] : null) ??
          "Extent couldn’t reach the server. Your folder link is still here, so you can try again.",
      );
    } finally {
      setFolderSubmitting(false);
    }
  };

  const retryPreparation = async () => {
    if (!workspace) return;
    setRetrying(true);
    setFolderError(null);
    try {
      setWorkspace(await retryWorkspace(workspace.workspaceId));
    } catch {
      setFolderError("Extent couldn’t restart file preparation. Try again.");
    } finally {
      setRetrying(false);
    }
  };

  const account = session?.status === "authenticated" ? session.account : null;
  const headerStatus =
    phase === "checking"
      ? "Checking connection"
      : phase === "connect"
        ? "Not connected"
        : phase === "folder"
          ? `${account?.email ?? "Google Drive"} · read-only`
          : `${workspace?.folder.name ?? "Preparing folder"} · ${account?.email ?? "Google Drive"}`;

  return (
    <div className="connect-shell">
      <ProductHeader action={<span>{headerStatus}</span>} />
      <main className="connect-main" id="main-content">
        <div className="connect-column">
          {phase === "checking" ? <CheckingConnection /> : null}
          {phase === "connect" ? (
            <ConnectState
              authMessage={initialAuthResult ? (authCopy[initialAuthResult] ?? null) : null}
              connectionError={connectionError}
              googleOauthAvailable={session?.googleOauthAvailable ?? true}
              onRetry={() => void loadSession()}
              referenceId={initialReferenceId}
              wasDisconnected={wasDisconnected}
            />
          ) : null}
          {phase === "folder" ? (
            <FolderState
              account={account}
              disconnecting={disconnecting}
              error={folderError ?? connectionError}
              folderSubmitting={folderSubmitting}
              folderUrl={folderUrl}
              onDisconnect={() => void disconnect()}
              onFolderChange={(value) => {
                setFolderUrl(value);
                setFolderError(null);
                idempotencyKey.current = null;
              }}
              onSubmit={(event) => void submitFolder(event)}
            />
          ) : null}
          {phase === "prepare" && workspace ? (
            <PreparationState
              error={folderError}
              onRetry={() => void retryPreparation()}
              retrying={retrying}
              workspace={workspace}
            />
          ) : null}
        </div>
      </main>
    </div>
  );
}

function CheckingConnection() {
  return (
    <div aria-live="polite" className="connect-state connect-state--checking">
      <div className="connect-intro">
        <h1>Choose what Extent can read.</h1>
        <p>
          Extent asks for read-only Drive access so it can open the folder link you provide.
        </p>
      </div>
      <p className="busy-line">
        <span aria-hidden="true" className="busy-dot" />
        Checking your Google connection
      </p>
    </div>
  );
}

function ConnectState({
  authMessage,
  connectionError,
  googleOauthAvailable,
  onRetry,
  referenceId,
  wasDisconnected,
}: {
  authMessage: string | null;
  connectionError: string | null;
  googleOauthAvailable: boolean;
  onRetry: () => void;
  referenceId: string | null;
  wasDisconnected: boolean;
}) {
  return (
    <section className="connect-state" aria-labelledby="connect-title">
      <div className="connect-intro">
        <h1 id="connect-title">Choose what Extent can read.</h1>
        <p>
          Extent asks for read-only Drive access so it can open the folder link you provide.
          Review what Extent reads, what stays in the browser, and which file types it
          supports.
        </p>
      </div>

      {wasDisconnected ? (
        <p className="side-note">
          Disconnected. Google access has been removed. Data prepared in earlier sessions is
          deleted separately, and that option is not available on this screen.
        </p>
      ) : null}

      <div className="consent-list">
        <p>
          Access is <strong>read-only</strong>. Extent cannot edit or delete anything in
          Drive.
        </p>
        <p>
          The folder link sets what Extent can read. It does not grant access by itself. The
          Google account you connect still controls which files Extent can open.
        </p>
        <p>Your Google credentials and document text are never stored in this browser.</p>
        <p>
          Disconnecting removes Extent’s Google access at any time. Deleting
          already-prepared data is a separate step.
        </p>
      </div>

      <div aria-live="polite" className="connect-feedback">
        {authMessage ? (
          <p className="message message--warning">
            {authMessage}
            {referenceId ? (
              <span className="message__reference"> Reference: {referenceId}</span>
            ) : null}
          </p>
        ) : null}
        {connectionError ? (
          <div className="message message--warning">
            <p>{connectionError}</p>
            <button className="text-button" onClick={onRetry} type="button">
              Try again
            </button>
          </div>
        ) : null}
        <div className="connect-actions">
          {googleOauthAvailable ? (
            <a className="button button--primary" href="/api/backend/v1/auth/google/start">
              Connect Google Drive
            </a>
          ) : (
            <button className="button button--disabled" disabled type="button">
              Google Drive unavailable
            </button>
          )}
          <Link className="text-link" href="/sample">
            Try the prepared sample instead
          </Link>
        </div>
        <p className="connect-footnote">
          The Alder Peak sample is prepared in advance and supports public questions. It is
          not connected to a visitor’s Drive account.
        </p>
      </div>
    </section>
  );
}

function FolderState({
  account,
  disconnecting,
  error,
  folderSubmitting,
  folderUrl,
  onDisconnect,
  onFolderChange,
  onSubmit,
}: {
  account: { displayName: string | null; email: string } | null;
  disconnecting: boolean;
  error: string | null;
  folderSubmitting: boolean;
  folderUrl: string;
  onDisconnect: () => void;
  onFolderChange: (value: string) => void;
  onSubmit: (event: FormSubmitEvent) => void;
}) {
  return (
    <section className="connect-state" aria-labelledby="folder-title">
      <div className="account-row">
        <p>
          Connected as{" "}
          <strong>
            {account?.displayName
              ? `${account.displayName} (${account.email})`
              : (account?.email ?? "Google Drive")}
          </strong>
          . Read-only access.
        </p>
        <button
          className="text-button"
          disabled={disconnecting}
          onClick={onDisconnect}
          type="button"
        >
          {disconnecting ? "Disconnecting…" : "Disconnect Google Drive"}
        </button>
      </div>
      <div className="connect-intro">
        <h1 id="folder-title">Paste a Google Drive folder link.</h1>
        <p>
          Extent will check access and read supported files in this folder and its
          subfolders. Files it cannot read will stay visible.
        </p>
      </div>
      <form className="folder-form" onSubmit={onSubmit}>
        <label htmlFor="folder-url">Google Drive folder link</label>
        <div className="input-row">
          <input
            aria-describedby={error ? "folder-error folder-help" : "folder-help"}
            aria-invalid={error ? true : undefined}
            autoComplete="url"
            id="folder-url"
            inputMode="url"
            onChange={(event) => {
              onFolderChange(event.target.value);
            }}
            placeholder="https://drive.google.com/drive/folders/…"
            required
            spellCheck={false}
            type="url"
            value={folderUrl}
          />
          <button
            className="button button--primary button--compact"
            disabled={folderSubmitting}
            type="submit"
          >
            {folderSubmitting ? "Checking folder…" : "Check this folder"}
          </button>
        </div>
        <p className="field-help" id="folder-help">
          The link chooses the folder. Your connected Google account still controls which
          files Extent can open. Supported file types are PDF, Google Docs, DOCX, CSV, plain
          text, and Markdown. Extent marks OCR text for verification.
        </p>
        {error ? (
          <p className="field-error" id="folder-error" role="alert">
            {error}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function PreparationState({
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
  const terminal = workspacePreparationIsTerminal(workspace);
  const files = adaptWorkspaceSources(workspace.sources);
  const unavailable =
    workspace.ingestion.failedFiles +
    workspace.ingestion.unsupportedFiles +
    workspace.ingestion.cappedFiles;
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
  const retryable =
    workspace.ingestion.status === "failed" || workspace.ingestion.status === "retryable";
  const canOpen = workspace.ingestion.readyFiles > 0 && terminal;

  return (
    <section className="connect-state preparation" aria-labelledby="preparation-title">
      <div className="preparation__intro">
        <p>{workspace.folder.name ?? "Google Drive folder"}</p>
        <div aria-live="polite" className="preparation__title-row">
          {!terminal ? <span aria-hidden="true" className="busy-dot" /> : null}
          <h1 id="preparation-title">{title}</h1>
        </div>
        <p>
          {formatDiscoverySummary(
            workspace.ingestion.discoveredFiles,
            workspace.ingestion.foldersVisited,
            workspace.ingestion.readyFiles,
            unavailable,
          )}
        </p>
      </div>

      {terminal ? (
        <div className="preparation__actions">
          {canOpen ? (
            <Link
              className="button button--primary"
              href={`/workspace/${workspace.workspaceId}`}
            >
              Open this folder
            </Link>
          ) : null}
          {retryable ? (
            <button
              className="button button--primary"
              disabled={retrying}
              onClick={onRetry}
              type="button"
            >
              {retrying ? "Trying again…" : "Try reading the folder again"}
            </button>
          ) : null}
          <p>
            {workspace.ingestion.status === "ready"
              ? "Every supported file is ready to search."
              : workspace.ingestion.status === "partial"
                ? `${formatCount(workspace.ingestion.readyFiles, "file")} ready to search. ${formatCount(unavailable, "file")} not checked. The file list remains below.`
                : "Extent will try reading this same folder again. It won’t create another copy."}
          </p>
        </div>
      ) : null}

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
              <span className={`file-state file-state--${file.tone}`}>{file.state}</span>
            </div>
          ))
        )}
      </div>

      {unavailable > 0 && terminal ? (
        <p className="side-note">
          Unavailable files stay listed. They may contain relevant evidence, and a result
          will say when this prevents a firm answer.
        </p>
      ) : null}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
