import assert from "node:assert/strict";
import { test } from "vitest";

import { readJsonResponse } from "../src/read-json-response.ts";

test("reads JSON and structured JSON media types", async () => {
  const json = await readJsonResponse(
    new Response(JSON.stringify({ workspaceId: "workspace-1" }), {
      headers: { "Content-Type": "application/json; charset=utf-8" },
    }),
  );
  const problem = await readJsonResponse(
    new Response(JSON.stringify({ message: "Workspace creation failed" }), {
      headers: { "Content-Type": "application/problem+json" },
      status: 500,
    }),
  );

  assert.deepEqual(json, { kind: "json", value: { workspaceId: "workspace-1" } });
  assert.deepEqual(problem, {
    kind: "json",
    value: { message: "Workspace creation failed" },
  });
});

test("classifies a non-JSON server response as unreadable", async () => {
  const body = await readJsonResponse(
    new Response("Internal Server Error", {
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      status: 500,
    }),
  );

  assert.deepEqual(body, { kind: "unreadable", reason: "unsupported_content_type" });
});

test("classifies malformed JSON as an invalid body", async () => {
  const body = await readJsonResponse(
    new Response("{", {
      headers: { "Content-Type": "application/json" },
      status: 500,
    }),
  );

  assert.deepEqual(body, { kind: "unreadable", reason: "invalid_json_body" });
});
