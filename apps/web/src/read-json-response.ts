export type JsonResponseBody =
  | { kind: "json"; value: unknown }
  | {
      kind: "unreadable";
      reason: "invalid_json_body" | "unsupported_content_type";
    };

export async function readJsonResponse(response: Response): Promise<JsonResponseBody> {
  const contentType = response.headers.get("content-type");
  const mediaType = contentType?.split(";", 1)[0]?.trim().toLowerCase();
  if (
    mediaType === undefined ||
    (mediaType !== "application/json" && !mediaType.endsWith("+json"))
  ) {
    return { kind: "unreadable", reason: "unsupported_content_type" };
  }

  try {
    const value: unknown = await response.json();
    return { kind: "json", value };
  } catch {
    return { kind: "unreadable", reason: "invalid_json_body" };
  }
}
