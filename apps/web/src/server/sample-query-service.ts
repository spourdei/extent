import "server-only";

import createClient from "openapi-fetch";

import {
  type ExtentApiPaths,
  type SampleWorkspaceProjection,
} from "../extent-api-contract.ts";
import { parseSampleWorkspaceProjection } from "../parse-sample-workspace-projection.ts";
import { ApiOriginConfigurationError, resolveApiOrigin } from "./api-origin.ts";

const sampleApiTimeoutMs = 8_000;

type SampleEndpoint = "/api/v1/demo/preview" | "/api/v1/demo/workspace";

export type SampleQueryServiceErrorCode =
  | "configuration"
  | "http_error"
  | "invalid_response"
  | "timeout"
  | "unavailable";

const errorMessage = {
  configuration: "The sample API is not configured safely.",
  http_error: "The sample API did not return a successful response.",
  invalid_response: "The sample API returned an invalid evidence projection.",
  timeout: "The sample API did not respond before the safety deadline.",
  unavailable: "The sample API could not be reached.",
} as const satisfies Record<SampleQueryServiceErrorCode, string>;

export class SampleQueryServiceError extends Error {
  readonly code: SampleQueryServiceErrorCode;
  readonly status: number | null;

  constructor(code: SampleQueryServiceErrorCode, status: number | null = null) {
    super(errorMessage[code]);
    this.name = "SampleQueryServiceError";
    this.code = code;
    this.status = status;
  }
}

const apiOrigin = (): string => {
  try {
    return resolveApiOrigin(process.env.EXTENT_API_INTERNAL_URL, process.env.VERCEL_ENV);
  } catch (error) {
    if (!(error instanceof ApiOriginConfigurationError)) {
      throw error;
    }
    throw new SampleQueryServiceError("configuration");
  }
};

const fetchSampleProjection = async (
  endpoint: SampleEndpoint,
): Promise<SampleWorkspaceProjection> => {
  const controller = new AbortController();
  const deadline = setTimeout(() => {
    controller.abort();
  }, sampleApiTimeoutMs);

  try {
    const client = createClient<ExtentApiPaths>({ baseUrl: apiOrigin() });
    const result = await client.GET(endpoint, {
      cache: "no-store",
      headers: { accept: "application/json" },
      parseAs: "text",
      signal: controller.signal,
    });
    if ("error" in result) {
      throw new SampleQueryServiceError("http_error", result.response.status);
    }
    const contentType = result.response.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json")) {
      throw new SampleQueryServiceError("invalid_response", result.response.status);
    }
    let payload: unknown;
    try {
      payload = JSON.parse(result.data);
    } catch {
      throw new SampleQueryServiceError("invalid_response", result.response.status);
    }
    try {
      return parseSampleWorkspaceProjection(payload);
    } catch {
      throw new SampleQueryServiceError("invalid_response", result.response.status);
    }
  } catch (error) {
    if (error instanceof SampleQueryServiceError) {
      throw error;
    }
    if (controller.signal.aborted) {
      throw new SampleQueryServiceError("timeout");
    }
    throw new SampleQueryServiceError("unavailable");
  } finally {
    clearTimeout(deadline);
  }
};

export const getSampleWorkspaceData = (): Promise<SampleWorkspaceProjection> =>
  fetchSampleProjection("/api/v1/demo/workspace");

export const getSyntheticPreviewData = (): Promise<SampleWorkspaceProjection> =>
  fetchSampleProjection("/api/v1/demo/preview");
