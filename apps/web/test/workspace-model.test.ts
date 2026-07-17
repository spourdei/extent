import assert from "node:assert/strict";
import { test } from "vitest";

import type { EvidencePassage, QuestionResult } from "../lib/types.ts";
import { adaptQuestionResults } from "../lib/workspace-model.ts";

function citation(blockId: string, sourceName: string, rawValue: string): EvidencePassage {
  return {
    blockId,
    driveFileId: `demo-${blockId}`,
    endExclusiveInBlock: rawValue.length,
    exactQuote: rawValue,
    lineStartOneBased: null,
    normalizedValue: rawValue.toLocaleLowerCase(),
    originKind: "pdf_page",
    pageIndexZeroBased: 0,
    path: ["Packet", sourceName],
    printedPageLabel: null,
    rawValue,
    role: "left",
    sourceName,
    startInBlock: 0,
  };
}

test("renders every evidence branch when several fields conflict", () => {
  const result: QuestionResult = {
    answerId: "10000000-0000-4000-8000-000000000001",
    claims: [
      {
        citations: [
          citation("20000000-0000-4000-8000-000000000001", "quote.pdf", "USD 1"),
          citation("20000000-0000-4000-8000-000000000002", "binder.pdf", "USD 2"),
        ],
        claimId: "30000000-0000-4000-8000-000000000001",
        relation: "conflict",
        text: "Premium: USD 1 / USD 2",
        value: null,
      },
      {
        citations: [
          citation("20000000-0000-4000-8000-000000000003", "quote.pdf", "USD 3"),
          citation("20000000-0000-4000-8000-000000000004", "binder.pdf", "USD 4"),
        ],
        claimId: "30000000-0000-4000-8000-000000000002",
        relation: "conflict",
        text: "Deductible: USD 3 / USD 4",
        value: null,
      },
    ],
    coverageGapReasons: [],
    createdAt: "2026-07-17T18:00:00Z",
    generationStatus: "completed",
    message: "Two conflicts found.",
    passages: [],
    policyVersion: "publication-policy-v1",
    question: "Which terms conflict?",
    questionId: "40000000-0000-4000-8000-000000000001",
    status: "conflict",
  };

  const adapted = adaptQuestionResults([result]).questions[0];

  assert.ok(adapted);
  assert.ok(adapted.comparisons);
  assert.equal(adapted.comparisons.length, 4);
  assert.deepEqual(
    adapted.comparisons.map((comparison) => comparison.caption),
    [
      "Premium: USD 1 / USD 2",
      "Premium: USD 1 / USD 2",
      "Deductible: USD 3 / USD 4",
      "Deductible: USD 3 / USD 4",
    ],
  );
});
