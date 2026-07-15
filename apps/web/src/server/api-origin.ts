const developmentApiOrigin = "http://127.0.0.1:8000";

export class ApiOriginConfigurationError extends Error {
  constructor() {
    super("The Extent API origin is not configured safely.");
    this.name = "ApiOriginConfigurationError";
  }
}

export const resolveApiOrigin = (
  configured: string | undefined,
  environment: string | undefined,
): string => {
  if (configured === undefined && environment === "production") {
    throw new ApiOriginConfigurationError();
  }
  const candidate = configured ?? developmentApiOrigin;
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new ApiOriginConfigurationError();
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    (environment === "production" && parsed.protocol !== "https:") ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.pathname !== "/" ||
    parsed.search !== "" ||
    parsed.hash !== ""
  ) {
    throw new ApiOriginConfigurationError();
  }
  return parsed.origin;
};
