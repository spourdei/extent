import { formatCount } from "./count-copy";
import type { EvidencePassage, QuestionResult, WorkspaceSource } from "./types";

export type DeskQuestionKind =
  | "supported"
  | "disagree"
  | "change"
  | "incomplete"
  | "passages"
  | "nosupport"
  | "failed";

export interface DeskEvidence {
  context: string;
  driveFileId?: string;
  file: string;
  highlight: string;
  id: string;
  locator: string;
  meta: readonly { label: string; value: string }[];
  ocr?: boolean;
  post: string;
  pre: string;
}

export interface DeskEvidenceRow {
  evidenceId: string;
  label: string;
  locator: string;
}

export interface DeskComparison {
  caption: string;
  evidenceId: string;
  locator: string;
  value: string;
}

export interface DeskTimelineItem extends DeskComparison {
  when: string;
}

export interface DeskQuestion {
  comparisons?: readonly DeskComparison[];
  coverage?: string;
  evidenceRows?: readonly DeskEvidenceRow[];
  evidenceHeading?: string;
  finding: string;
  id: string;
  kind: DeskQuestionKind;
  note?: string;
  passages?: readonly DeskEvidenceRow[];
  passagesHeading?: string;
  passagesNote?: string;
  shortTitle: string;
  stateLabel: string;
  timeline?: readonly DeskTimelineItem[];
  title: string;
  unavailable?: readonly { name: string; reason: string }[];
  unavailableNote?: string;
}

export interface DeskFile {
  folder: string;
  id?: string;
  name: string;
  state: string;
  tone: "danger" | "muted" | "success" | "warning";
}

export interface DeskResultSet {
  evidence: Readonly<Record<string, DeskEvidence>>;
  questions: readonly DeskQuestion[];
}

function locatorFor(passage: EvidencePassage): string {
  if (passage.originKind === "pdf_page" && passage.pageIndexZeroBased !== null) {
    return passage.printedPageLabel ?? `Page ${String(passage.pageIndexZeroBased + 1)}`;
  }
  return passage.lineStartOneBased === null
    ? "Exact passage"
    : `Line ${String(passage.lineStartOneBased)}`;
}

function pathFolder(path: readonly string[]): string {
  const parent = path.slice(0, -1).join("/");
  return parent.length > 0 ? `/${parent}/` : "/";
}

function splitHighlight(quote: string, preferred: string | null): [string, string, string] {
  const candidate = preferred?.trim();
  if (candidate) {
    const index = quote.toLocaleLowerCase().indexOf(candidate.toLocaleLowerCase());
    if (index >= 0) {
      return [
        quote.slice(0, index),
        quote.slice(index, index + candidate.length),
        quote.slice(index + candidate.length),
      ];
    }
  }
  return ["", quote, ""];
}

function passageEvidence(
  passage: EvidencePassage,
  id: string,
  context: string,
): DeskEvidence {
  const [pre, highlight, post] = splitHighlight(
    passage.exactQuote,
    passage.rawValue ?? passage.normalizedValue,
  );
  return {
    context,
    ...(passage.driveFileId.startsWith("demo-")
      ? {}
      : { driveFileId: passage.driveFileId }),
    file: passage.sourceName,
    highlight,
    id,
    locator: locatorFor(passage),
    meta: [
      { label: "Folder", value: pathFolder(passage.path) },
      ...(passage.normalizedValue
        ? [{ label: "Value used", value: passage.normalizedValue }]
        : []),
    ],
    post,
    pre,
  };
}

function resultKind(result: QuestionResult): DeskQuestionKind {
  if (result.policyVersion === "clarification-policy-v1") return "incomplete";
  if (result.policyVersion === "source-state-policy-v1") {
    return result.coverageGapReasons.length > 0 ? "incomplete" : "nosupport";
  }
  if (result.generationStatus === "failed") return "failed";
  if (result.status === "conflict") return "disagree";
  if (result.status === "changed") return "change";
  if (result.status === "coverage_limited") return "incomplete";
  if (result.status === "evidence_supported" && result.claims.length > 0) {
    return "supported";
  }
  if (result.status === "evidence_retrieved" || result.passages.length > 0) {
    return "passages";
  }
  return "nosupport";
}

function stateLabel(result: QuestionResult, kind: DeskQuestionKind): string {
  if (result.policyVersion === "clarification-policy-v1") return "Clarification needed";
  if (result.policyVersion === "source-state-policy-v1") return "File status";
  if (result.policyVersion === "structured-analysis-policy-v1") {
    if (result.status === "coverage_limited") return "Partial calculation";
    return result.claims.length > 0 ? "Calculated result" : "Calculation incomplete";
  }
  if (
    result.policyVersion === "exhaustive-extraction-policy-v1" ||
    result.policyVersion === "exhaustive-premium-policy-v1"
  ) {
    if (result.status === "coverage_limited") return "Partial extraction";
    return result.claims.length > 0 ? "Values extracted" : "Extraction complete";
  }
  return {
    change: "Change found",
    disagree: "Sources disagree",
    failed: "Answer unavailable",
    incomplete: "No firm answer",
    nosupport: "Search complete",
    passages: "Relevant passages found",
    supported: "Evidence found",
  }[kind];
}

function coverageReasonLabel(reason: QuestionResult["coverageGapReasons"][number]): string {
  return {
    capped: "At least one file was not processed in this earlier folder run.",
    failed: "Extent couldn’t read at least one file.",
    inaccessible: "The connected account couldn’t open at least one file.",
    processing: "At least one file was still being read.",
    unknown_branch: "Extent couldn’t check part of the folder.",
    unsafe_to_parse: "Extent couldn’t read at least one file.",
    unstable: "At least one file changed while Extent was reading it.",
    unsupported: "Extent can’t read at least one file type in this folder yet.",
  }[reason];
}

function isCompleteDataPolicy(result: QuestionResult): boolean {
  return (
    result.policyVersion === "exhaustive-extraction-policy-v1" ||
    result.policyVersion === "exhaustive-premium-policy-v1" ||
    result.policyVersion === "structured-analysis-policy-v1"
  );
}

function shortTitle(question: string): string {
  return question.length > 48 ? `${question.slice(0, 46)}…` : question;
}

function extractionFinding(result: QuestionResult): string {
  const count = result.claims.length;
  const countCopy = formatCount(count, "matching value");
  const hasKnownFileGaps = result.coverageGapReasons.length > 0;

  if (result.message.startsWith("More than 200 matching entries were found")) {
    return "Extent found more than 200 matching values. Ask for a more specific field so every value can be shown with its source.";
  }
  if (count > 0 && result.status === "coverage_limited") {
    return hasKnownFileGaps
      ? `Found ${countCopy} in a partial extraction. Some files weren’t available, so this list may not include every matching value in the folder.`
      : `Found ${countCopy}, but Extent couldn’t complete the folder-wide result. Review each value with its exact quote and source location.`;
  }
  if (count > 0) {
    return `Found ${countCopy}. Review each value with its exact quote and source location.`;
  }
  if (result.status === "coverage_limited") {
    return hasKnownFileGaps
      ? "No matching values were found in the files Extent could check. Some files weren’t available, so this is not a complete folder-wide result."
      : "Extent couldn’t complete the folder-wide result. Review the files or ask a more specific question.";
  }
  return "No matching values were found in the files Extent checked.";
}

function clarificationFinding(message: string): string {
  const knownCopy: Readonly<Record<string, string>> = {
    "Ask for one labeled field at a time, or quote a compound field name.":
      "Ask for one field at a time, or put a compound field name in quotation marks.",
    "Name one labeled field to extract—for example, “List every renewal date.”":
      "Name one value to find. For example: “List every renewal date.”",
    "Use a shorter label for one field to extract.":
      "Use a shorter name for the value you want to find.",
    "Which prior value or subject do you mean?":
      "Which earlier value or subject do you mean?",
  };
  return (
    knownCopy[message] ??
    "Extent needs a more specific question. Name the value, document, or time period you want to check."
  );
}

function resultFinding(result: QuestionResult): string {
  if (result.policyVersion === "clarification-policy-v1") {
    return clarificationFinding(result.message);
  }
  if (result.policyVersion === "source-state-policy-v1") {
    return result.coverageGapReasons.length > 0
      ? "Extent checked the folder’s current file status. Some files weren’t available. Review the file list for details."
      : "Extent checked the folder’s current file status. Review the file list to see what is ready.";
  }
  if (result.policyVersion === "structured-analysis-policy-v1") {
    if (result.claims.length > 0) {
      return result.claims.map((claim) => claim.text).join(" ");
    }
    return result.status === "coverage_limited"
      ? "Extent couldn’t complete this calculation from every required row."
      : "Extent couldn’t produce a supported calculated result.";
  }
  if (isCompleteDataPolicy(result)) return extractionFinding(result);
  if (result.generationStatus === "failed") {
    return result.passages.length > 0
      ? "We couldn’t finish the answer. The relevant passages Extent found are still available below."
      : "We couldn’t finish the answer. Try asking the question again.";
  }
  if (result.status === "coverage_limited") {
    return result.coverageGapReasons.length > 0
      ? "We couldn’t confirm this because some files weren’t available. Extent searched the files it could read. The unavailable files may still contain relevant evidence."
      : "We couldn’t support a firm answer from the files Extent checked. Review the available evidence or ask a more specific question.";
  }
  if (result.claims.length > 0) {
    return result.claims.map((claim) => claim.text).join(" ");
  }
  if (result.passages.length > 0 || result.status === "evidence_retrieved") {
    return "We found relevant passages, but not enough for a supported finding.";
  }
  return "We couldn’t find evidence for this. Extent checked every available file in this folder and didn’t find source text that supports an answer.";
}

export function adaptQuestionResults(results: readonly QuestionResult[]): DeskResultSet {
  const evidence: Record<string, DeskEvidence> = {};
  const questions = results.map((result): DeskQuestion => {
    const kind = resultKind(result);
    const citations = result.claims.flatMap((claim) =>
      claim.citations.map((passage, index) => ({
        citationIndex: index,
        claim,
        evidenceId: `${result.answerId}:claim:${claim.claimId}:${String(index)}`,
        passage,
      })),
    );
    const loosePassages = result.passages.map((passage, index) => ({
      evidenceId: `${result.answerId}:passage:${passage.blockId}:${String(index)}`,
      passage,
    }));

    for (const item of citations) {
      evidence[item.evidenceId] = passageEvidence(
        item.passage,
        item.evidenceId,
        item.claim.text,
      );
    }
    for (const item of loosePassages) {
      evidence[item.evidenceId] = passageEvidence(
        item.passage,
        item.evidenceId,
        "Relevant passage, not a supported finding",
      );
    }

    const finding = resultFinding(result);
    const coverage =
      result.coverageGapReasons.length > 0
        ? `Some files weren’t available to check. ${[...new Set(result.coverageGapReasons.map(coverageReasonLabel))].join(" ")} This limit stays with the result.`
        : undefined;

    const common = {
      ...(coverage ? { coverage } : {}),
      finding,
      id: result.answerId,
      kind,
      shortTitle: shortTitle(result.question),
      stateLabel: stateLabel(result, kind),
      title: result.question,
    } satisfies DeskQuestion;

    if (result.claims.length > 0 && kind !== "disagree" && kind !== "change") {
      const calculated = result.policyVersion === "structured-analysis-policy-v1";
      return {
        ...common,
        ...(calculated ? { evidenceHeading: "Calculation lineage" } : {}),
        evidenceRows: citations.map(({ citationIndex, claim, evidenceId, passage }) => ({
          evidenceId,
          label: calculated
            ? claim.citations.length > 1
              ? citationIndex === 0
                ? "First contributing row"
                : "Last contributing row"
              : "Contributing row"
            : (claim.value ?? claim.text),
          locator: `${passage.sourceName} · ${locatorFor(passage)}`,
        })),
        ...(calculated
          ? {
              note: "This result was calculated across every matched row. The rows shown are representative lineage; the calculated value does not appear verbatim in either row.",
            }
          : {}),
      };
    }
    if (kind === "disagree") {
      const comparisons = citations.map(({ claim, evidenceId, passage }, index) => ({
        caption: claim.text,
        evidenceId,
        locator: `${passage.sourceName} · ${locatorFor(passage)}`,
        value:
          passage.normalizedValue ??
          passage.rawValue ??
          claim.value ??
          `Source ${String(index + 1)}`,
      }));
      return {
        ...common,
        comparisons,
        note: "Extent found support for each value and did not choose between them. Inspect both sources before relying on either.",
      };
    }
    if (kind === "change") {
      const ordered = citations
        .filter(({ passage }) => passage.role === "before" || passage.role === "after")
        .sort((a, b) =>
          a.passage.role === "before" && b.passage.role !== "before" ? -1 : 1,
        );
      return {
        ...common,
        timeline: ordered.slice(0, 2).map(({ claim, evidenceId, passage }, index) => ({
          caption: claim.text,
          evidenceId,
          locator: `${passage.sourceName} · ${locatorFor(passage)}`,
          value:
            passage.normalizedValue ??
            passage.rawValue ??
            claim.value ??
            "Value shown in source",
          when: `${index === 0 ? "Earlier" : "Later"} · ${passage.sourceName}`,
        })),
      };
    }
    if (
      kind === "passages" ||
      (loosePassages.length > 0 &&
        (kind === "failed" ||
          (kind === "incomplete" && result.policyVersion !== "clarification-policy-v1")))
    ) {
      return {
        ...common,
        passages: loosePassages.map(({ evidenceId, passage }) => ({
          evidenceId,
          label: passage.exactQuote,
          locator: `${passage.sourceName} · ${locatorFor(passage)}`,
        })),
        passagesHeading: "Relevant passages",
        passagesNote:
          kind === "failed"
            ? "Review these passages below or try the question again."
            : kind === "incomplete"
              ? "These passages may help, but they do not cover the full folder."
              : "Review these passages or ask a more specific question. They are not a supported finding.",
      };
    }
    return common;
  });
  return { evidence, questions };
}

export function adaptWorkspaceSources(
  sources: readonly WorkspaceSource[],
): readonly DeskFile[] {
  return sources.map((source) => {
    const folder = pathFolder(source.path);
    if (source.status === "ready") {
      const common = { folder, id: source.driveFileId, name: source.name };
      if (source.mimeType === "application/csv" || source.mimeType === "text/csv") {
        return {
          ...common,
          state: `${formatCount(source.blockCount, "row excerpt")} · ready to search by line`,
          tone: "success",
        };
      }
      if (
        source.mimeType ===
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      ) {
        return {
          ...common,
          state: `${formatCount(source.blockCount, "paragraph or table excerpt")} · ready to search by line`,
          tone: "success",
        };
      }
      return {
        ...common,
        state:
          source.extractionMethod === "ocr"
            ? source.pageCount === null
              ? "OCR text · verify against Drive"
              : `${formatCount(source.pageCount, "page")} · OCR text · verify against Drive`
            : source.pageCount !== null
              ? `${formatCount(source.pageCount, "page")} · ready to search`
              : `${formatCount(source.blockCount, "excerpt")} · ready to search by line`,
        tone: source.extractionMethod === "ocr" ? "warning" : "success",
      };
    }
    if (source.status === "queued") {
      return {
        folder,
        id: source.driveFileId,
        name: source.name,
        state: "Waiting to be read",
        tone: "muted",
      };
    }
    if (source.status === "parsing") {
      return {
        folder,
        id: source.driveFileId,
        name: source.name,
        state: "Reading this file",
        tone: "muted",
      };
    }
    if (source.status === "unsupported") {
      return {
        folder,
        id: source.driveFileId,
        name: source.name,
        state: "Extent can’t read this file type yet",
        tone: "danger",
      };
    }
    if (source.status === "capped") {
      return {
        folder,
        id: source.driveFileId,
        name: source.name,
        state:
          source.errorCode === "file_size_limit" || source.reasonCode === "file_size_limit"
            ? "This file is larger than the processing limit"
            : "Not processed in this earlier folder run",
        tone: "danger",
      };
    }
    const failureLabels: Readonly<Record<string, string>> = {
      docx_archive_too_large: "This DOCX is too large for Extent to read",
      embedding_input_invalid: "Extent couldn’t prepare this file for search",
      embedding_provider_unavailable: "Search preparation is temporarily unavailable",
      embedding_response_invalid: "Extent couldn’t prepare this file for search",
      encrypted_pdf: "Password-protected PDF",
      inaccessible: "The connected account can’t open this file",
      invalid_csv: "Extent couldn’t read this CSV",
      invalid_docx: "Extent couldn’t read this DOCX",
      invalid_encoding: "Extent couldn’t read this text file",
      invalid_xlsx: "Extent couldn’t read this spreadsheet",
      invalid_pdf: "Extent couldn’t read this PDF",
      no_text: "Extent couldn’t find readable text in this file",
      not_found: "This file is no longer in the folder",
      ocr_engine_unavailable: "OCR isn’t available right now",
      ocr_no_text: "OCR couldn’t find readable text in this file",
      ocr_recognition_failed: "Extent couldn’t recognize the text in this PDF",
      ocr_render_failed: "Extent couldn’t prepare this PDF for OCR",
      ocr_timeout: "OCR took too long and can be retried",
      provider_failure: "Google Drive couldn’t provide this file",
      rate_limited: "Google Drive asked Extent to wait",
      retry_exhausted: "Extent still couldn’t read this file after retrying",
    };
    const reason =
      failureLabels[source.errorCode ?? ""] ??
      failureLabels[source.reasonCode ?? ""] ??
      "Extent couldn’t finish reading this file";
    return {
      folder,
      id: source.driveFileId,
      name: source.name,
      state: reason,
      tone: "danger",
    };
  });
}
