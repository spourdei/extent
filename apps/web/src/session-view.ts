import type { components } from "./generated/extent-api.ts";
import { readJsonResponse } from "./read-json-response.ts";

export type SessionView =
  | components["schemas"]["AuthenticatedSessionView"]
  | components["schemas"]["SignedOutSessionView"];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hasOnlyKeys = (value: Record<string, unknown>, keys: readonly string[]): boolean =>
  Object.keys(value).every((key) => keys.includes(key)) &&
  keys.every((key) => Object.hasOwn(value, key));

const isBoundedString = (
  value: unknown,
  minimum: number,
  maximum: number,
): value is string =>
  typeof value === "string" && value.length >= minimum && value.length <= maximum;

const isSessionView = (value: unknown): value is SessionView => {
  if (!isRecord(value) || typeof value.status !== "string") return false;
  if (value.status === "signed_out") {
    return (
      hasOnlyKeys(value, ["googleOauthAvailable", "status"]) &&
      typeof value.googleOauthAvailable === "boolean"
    );
  }
  if (
    value.status !== "authenticated" ||
    !hasOnlyKeys(value, ["account", "expiresAt", "googleOauthAvailable", "status"]) ||
    value.googleOauthAvailable !== true ||
    !isRecord(value.account) ||
    !hasOnlyKeys(value.account, ["displayName", "email"]) ||
    !isBoundedString(value.account.email, 3, 320) ||
    !(
      value.account.displayName === null ||
      isBoundedString(value.account.displayName, 1, 200)
    ) ||
    !isBoundedString(value.expiresAt, 1, 80)
  ) {
    return false;
  }
  return !Number.isNaN(Date.parse(value.expiresAt));
};

export const parseSessionView = (value: unknown): SessionView => {
  if (!isSessionView(value)) throw new Error("invalid session response");
  return value;
};

export const readSessionView = async (response: Response): Promise<SessionView> => {
  if (!response.ok) throw new Error("session request failed");
  const responseBody = await readJsonResponse(response);
  if (responseBody.kind !== "json") throw new Error("session response unreadable");
  return parseSessionView(responseBody.value);
};
