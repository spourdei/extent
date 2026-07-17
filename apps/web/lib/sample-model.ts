import type { SampleWorkspaceProjection } from "../src/extent-api-contract";
import { formatCount } from "./count-copy";
import type {
  DeskComparison,
  DeskEvidence,
  DeskEvidenceRow,
  DeskFile,
  DeskQuestion,
  DeskQuestionKind,
  DeskTimelineItem,
} from "./workspace-model";

export interface SampleWorkspaceModel {
  readonly coverageLabel: string;
  readonly evidence: Readonly<Record<string, DeskEvidence>>;
  readonly files: readonly DeskFile[];
  readonly folderTitle: string;
  readonly questions: readonly DeskQuestion[];
  readonly readyFiles: number;
  readonly sampleLabel: string;
  readonly totalFiles: number;
}

type SampleView = SampleWorkspaceProjection["execution"]["view"];
type PublishedClaim = SampleView["claims"][number];
type Citation = SampleView["citations"][number];
type CitationContext = SampleWorkspaceProjection["citationContexts"][number];

function shortTitle(question: string): string {
  return question.length > 48 ? `${question.slice(0, 46)}…` : question;
}

function formatObservedAt(value: string): string {
  const date = new Date(value);
  const dateLabel = new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(date);
  const timeLabel = `${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")}`;
  return `${dateLabel}, ${timeLabel} UTC`;
}

function terminalKind(status: SampleView["terminal"]["status"]): DeskQuestionKind {
  if (status === "evidence_supported") return "supported";
  if (status === "changed") return "change";
  if (status === "conflict" || status === "precedence_unknown") return "disagree";
  return "passages";
}

function terminalLabel(kind: DeskQuestionKind): string {
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

function splitQuote(
  before: string,
  quote: string,
  after: string,
  preferred: string,
): { highlight: string; post: string; pre: string } {
  const index = quote.toLocaleLowerCase().indexOf(preferred.toLocaleLowerCase());
  if (index === -1) {
    return { highlight: quote, post: after, pre: before };
  }
  return {
    highlight: quote.slice(index, index + preferred.length),
    post: `${quote.slice(index + preferred.length)}${after}`,
    pre: `${before}${quote.slice(0, index)}`,
  };
}

function resolveCitation(
  citationId: string,
  view: SampleView,
  contexts: readonly CitationContext[],
): { citation: Citation; context: CitationContext } {
  const citation = view.citations.find((item) => item.citationId === citationId);
  const context = contexts.find((item) => item.citationId === citationId);
  if (citation === undefined || context === undefined) {
    throw new Error("The prepared sample contained an unresolved evidence citation.");
  }
  return { citation, context };
}

function evidenceFor(
  claim: PublishedClaim,
  citation: Citation,
  context: CitationContext,
  revisionLabel: string | null,
): DeskEvidence {
  const split = splitQuote(
    context.passageBefore,
    citation.quote,
    context.passageAfter,
    claim.lineage.normalizedValue.literal,
  );
  const applicability = claim.lineage.applicability;
  return {
    context: claim.text,
    file: context.fileName,
    highlight: split.highlight,
    id: citation.citationId,
    locator: context.locatorLabel,
    meta: [
      { label: "Subject", value: applicability.entity },
      { label: "Field", value: applicability.field },
      { label: "Applies to", value: applicability.scope },
      { label: "Period", value: applicability.periodLabel },
      { label: "Value used", value: claim.lineage.normalizedValue.literal },
      {
        label: "Source version",
        value: revisionLabel ?? claim.lineage.documentVersionId,
      },
      { label: "Seen by Extent", value: formatObservedAt(context.observedAt) },
    ],
    post: split.post,
    pre: split.pre,
  };
}

function evidenceRows(
  claims: readonly PublishedClaim[],
  view: SampleView,
  contexts: readonly CitationContext[],
): readonly DeskEvidenceRow[] {
  return claims.flatMap((claim) =>
    claim.citationIds.map((citationId) => {
      const { context } = resolveCitation(citationId, view, contexts);
      return {
        evidenceId: citationId,
        label: claim.lineage.normalizedValue.literal,
        locator: `${context.fileName} · ${context.locatorLabel}`,
      };
    }),
  );
}

function comparisons(
  claims: readonly PublishedClaim[],
  view: SampleView,
  contexts: readonly CitationContext[],
): readonly DeskComparison[] {
  return claims.flatMap((claim) => {
    const citationId = claim.citationIds.at(0);
    if (citationId === undefined) return [];
    const { context } = resolveCitation(citationId, view, contexts);
    return [
      {
        caption: claim.text,
        evidenceId: citationId,
        locator: `${context.fileName} · ${context.locatorLabel}`,
        value: claim.lineage.normalizedValue.literal,
      },
    ];
  });
}

function timeline(
  claims: readonly PublishedClaim[],
  view: SampleView,
  contexts: readonly CitationContext[],
): readonly DeskTimelineItem[] {
  return comparisons(claims, view, contexts)
    .map((item) => {
      const context = contexts.find(
        (candidate) => candidate.citationId === item.evidenceId,
      );
      if (context === undefined) {
        throw new Error("The prepared sample was missing timeline evidence context.");
      }
      return { ...item, observedAt: context.observedAt };
    })
    .sort((left, right) => left.observedAt.localeCompare(right.observedAt))
    .map((item, index, items) => ({
      caption: item.caption,
      evidenceId: item.evidenceId,
      locator: item.locator,
      value: item.value,
      when: `${index === items.length - 1 ? "Later" : "Earlier"} · ${item.observedAt}`,
    }));
}

export function adaptSampleWorkspace(
  sample: SampleWorkspaceProjection,
): SampleWorkspaceModel {
  const { view } = sample.execution;
  if (view.claims.length === 0) {
    throw new Error("The prepared sample did not contain a published finding.");
  }

  const evidence: Record<string, DeskEvidence> = {};
  for (const claim of view.claims) {
    for (const citationId of claim.citationIds) {
      const { citation, context } = resolveCitation(
        citationId,
        view,
        sample.citationContexts,
      );
      evidence[citationId] = evidenceFor(
        claim,
        citation,
        context,
        sample.workspace.revisionLabel,
      );
    }
  }
  if (Object.keys(evidence).length === 0) {
    throw new Error("The prepared sample did not contain inspectable evidence.");
  }

  const kind = terminalKind(view.terminal.status);
  const rows = evidenceRows(view.claims, view, sample.citationContexts);
  const gapReasons = view.revision.coverage.gapReasons;
  const questionComparisons =
    kind === "disagree" ? comparisons(view.claims, view, sample.citationContexts) : null;
  const questionTimeline =
    kind === "change" ? timeline(view.claims, view, sample.citationContexts) : null;
  const question: DeskQuestion = {
    coverage:
      gapReasons.length === 0
        ? `Extent checked ${formatCount(view.revision.coverage.ready, "prepared document version")}.`
        : "Some prepared files could not be checked.",
    ...(kind === "supported" ? { evidenceRows: rows } : {}),
    finding: view.claims.map((claim) => claim.text).join(" "),
    id: view.answerId,
    kind,
    ...(kind === "passages"
      ? {
          passages: rows,
          passagesHeading: "Relevant passages",
          passagesNote:
            "Review these passages before deciding how to use the prepared result.",
        }
      : {}),
    ...(questionComparisons
      ? {
          comparisons: questionComparisons,
          note: "Extent found support for both values and did not choose between them.",
        }
      : {}),
    shortTitle: shortTitle(sample.question),
    stateLabel: terminalLabel(kind),
    ...(questionTimeline ? { timeline: questionTimeline } : {}),
    title: sample.question,
  };

  const readyFiles = view.revision.coverage.ready;
  const totalFiles = view.revision.coverage.discovered;
  return {
    coverageLabel: `${String(readyFiles)} of ${formatCount(totalFiles, "file")} checked`,
    evidence,
    files: sample.workspace.sources.map(
      (source): DeskFile => ({
        folder: "/Prepared sample/",
        id: source.documentVersionId,
        name: source.fileName,
        state:
          source.status === "unsupported"
            ? (source.reason ?? "Unsupported file type")
            : source.selected
              ? "Quoted in this finding"
              : source.evaluated
                ? "Checked for support"
                : "Ready",
        tone: source.status === "unsupported" ? "muted" : "success",
      }),
    ),
    folderTitle: sample.workspace.name,
    questions: [question],
    readyFiles,
    sampleLabel: sample.workspace.sampleLabel,
    totalFiles,
  };
}
