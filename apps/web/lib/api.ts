import { readQuestionResult } from "../src/parse-workspace-question-result";
import { readWorkspaceError, readWorkspaceView } from "../src/parse-workspace-view";
import { readJsonResponse } from "../src/read-json-response";
import { parseSessionView } from "../src/session-view";
import type { QuestionResult, SessionView, WorkspaceView } from "./types";

const requestTimeoutMs = 15_000;

export class ApiRequestError extends Error {
  readonly code: string;
  readonly reasonCode: string | null;
  readonly status: number | null;

  constructor(
    code: string,
    message: string,
    status: number | null = null,
    reasonCode: string | null = null,
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.reasonCode = reasonCode;
    this.status = status;
  }
}

async function request(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = requestTimeoutMs,
): Promise<{ body: unknown; response: Response }> {
  const controller = new AbortController();
  const timeoutError = new ApiRequestError(
    "request_timed_out",
    "Extent did not respond before the request timed out.",
  );
  const abortFromCaller = () => {
    controller.abort();
  };
  if (init.signal?.aborted === true) controller.abort();
  else init.signal?.addEventListener("abort", abortFromCaller, { once: true });
  const deadline = globalThis.setTimeout(() => {
    controller.abort(timeoutError);
  }, timeoutMs);

  try {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    const response = await fetch(path, {
      cache: "no-store",
      credentials: "include",
      ...init,
      headers,
      signal: controller.signal,
    });
    const responseBody = await readJsonResponse(response);
    return {
      body: responseBody.kind === "json" ? responseBody.value : null,
      response,
    };
  } catch (error) {
    if (controller.signal.reason === timeoutError) throw timeoutError;
    throw error;
  } finally {
    globalThis.clearTimeout(deadline);
    init.signal?.removeEventListener("abort", abortFromCaller);
  }
}

function responseError(
  body: unknown,
  response: Response,
  fallbackCode: string,
  fallbackMessage: string,
): ApiRequestError {
  const parsed = readWorkspaceError(body);
  return new ApiRequestError(
    parsed?.code ?? fallbackCode,
    parsed?.message ?? fallbackMessage,
    response.status,
    parsed?.reasonCode ?? null,
  );
}

function invalidResponse(code: string): ApiRequestError {
  return new ApiRequestError(
    code,
    "Extent returned a response that did not match its published API contract.",
  );
}

export async function getSession(signal?: AbortSignal): Promise<SessionView> {
  const { body, response } = await request(
    "/api/backend/v1/auth/session",
    signal ? { signal } : {},
  );
  if (!response.ok) {
    throw responseError(
      body,
      response,
      "session_unavailable",
      "Extent could not verify the current session.",
    );
  }
  try {
    return parseSessionView(body);
  } catch {
    throw invalidResponse("session_response_invalid");
  }
}

export async function disconnectSession(): Promise<void> {
  const { body, response } = await request("/api/backend/v1/auth/session", {
    method: "DELETE",
  });
  if (!response.ok) {
    throw responseError(
      body,
      response,
      "disconnect_failed",
      "Extent could not remove the current Google session.",
    );
  }
}

export async function createWorkspace(
  folderUrl: string,
  idempotencyKey: string,
): Promise<WorkspaceView> {
  const { body, response } = await request("/api/backend/v1/workspaces", {
    body: JSON.stringify({ folderUrl }),
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    method: "POST",
  });
  if (!response.ok) {
    throw responseError(
      body,
      response,
      "workspace_create_failed",
      "Extent could not prepare this folder.",
    );
  }
  const workspace = readWorkspaceView(body);
  if (workspace === null) throw invalidResponse("workspace_response_invalid");
  return workspace;
}

export async function getWorkspace(
  id: string,
  signal?: AbortSignal,
): Promise<WorkspaceView> {
  const { body, response } = await request(
    `/api/backend/v1/workspaces/${encodeURIComponent(id)}`,
    signal ? { signal } : {},
  );
  if (!response.ok) {
    throw responseError(
      body,
      response,
      "workspace_unavailable",
      "Extent could not open this workspace.",
    );
  }
  const workspace = readWorkspaceView(body);
  if (workspace === null) throw invalidResponse("workspace_response_invalid");
  return workspace;
}

export async function retryWorkspace(id: string): Promise<WorkspaceView> {
  const { body, response } = await request(
    `/api/backend/v1/workspaces/${encodeURIComponent(id)}/retry`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw responseError(
      body,
      response,
      "workspace_retry_failed",
      "Extent could not restart file preparation.",
    );
  }
  const workspace = readWorkspaceView(body);
  if (workspace === null) throw invalidResponse("workspace_response_invalid");
  return workspace;
}

export async function askWorkspace(
  id: string,
  question: string,
  idempotencyKey: string,
): Promise<QuestionResult> {
  const { body, response } = await request(
    `/api/backend/v1/workspaces/${encodeURIComponent(id)}/messages`,
    {
      body: JSON.stringify({ question }),
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      method: "POST",
    },
  );
  if (!response.ok) {
    throw responseError(
      body,
      response,
      "question_failed",
      "Extent could not complete this question.",
    );
  }
  const result = readQuestionResult(body);
  if (result === null) throw invalidResponse("question_response_invalid");
  return result;
}

export async function askDemoQuestion(
  question: string,
  idempotencyKey: string,
): Promise<QuestionResult> {
  const { body, response } = await request(
    "/api/backend/v1/demo/questions",
    {
      body: JSON.stringify({ question }),
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      method: "POST",
    },
    60_000,
  );
  if (!response.ok) {
    throw responseError(
      body,
      response,
      "question_failed",
      "Extent could not complete this sample question.",
    );
  }
  const result = readQuestionResult(body);
  if (result === null) throw invalidResponse("question_response_invalid");
  return result;
}

export function apiErrorCode(error: unknown): string | null {
  return error instanceof ApiRequestError ? error.code : null;
}
