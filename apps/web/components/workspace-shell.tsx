"use client";

import Link from "next/link";
import {
  type RefObject,
  type SyntheticEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { apiErrorCode } from "../lib/api";
import { formatCount, formatCoverageSummary } from "../lib/count-copy";
import type { QuestionResult } from "../lib/types";
import {
  adaptQuestionResults,
  type DeskEvidence,
  type DeskFile,
  type DeskQuestion,
  type DeskResultSet,
} from "../lib/workspace-model";
import { Wordmark } from "./product-header";

export type WorkspaceMode = "live" | "sample";
type FormSubmitEvent = SyntheticEvent<HTMLFormElement, SubmitEvent>;

export function WorkspaceShell({
  coverageLabel,
  evidence: initialEvidence,
  files,
  folderTitle,
  mode,
  onAsk,
  onRefresh,
  questions: initialQuestions,
  readyFiles,
  refreshError,
  totalFiles,
}: {
  coverageLabel: string;
  evidence: Readonly<Record<string, DeskEvidence>>;
  files: readonly DeskFile[];
  folderTitle: string;
  mode: WorkspaceMode;
  onAsk?: (question: string) => Promise<QuestionResult>;
  onRefresh?: () => void;
  questions: readonly DeskQuestion[];
  readyFiles: number;
  refreshError?: string | null;
  totalFiles: number;
}) {
  const [questions, setQuestions] = useState<readonly DeskQuestion[]>(initialQuestions);
  const [evidence, setEvidence] =
    useState<Readonly<Record<string, DeskEvidence>>>(initialEvidence);
  const [activeId, setActiveId] = useState(initialQuestions[0]?.id ?? null);
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);
  const [questionText, setQuestionText] = useState("");
  const [processingTitle, setProcessingTitle] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const coverageDialogRef = useRef<HTMLDialogElement>(null);
  const evidencePanelRef = useRef<HTMLElement>(null);
  const lastTriggerRef = useRef<HTMLElement | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && coverageDialogRef.current?.open === true) {
        event.preventDefault();
        coverageDialogRef.current.close();
        return;
      }
      if (event.key === "Escape" && activeEvidenceId !== null) {
        setActiveEvidenceId(null);
        window.setTimeout(() => lastTriggerRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [activeEvidenceId]);

  useEffect(() => {
    if (activeEvidenceId !== null) evidencePanelRef.current?.focus({ preventScroll: true });
  }, [activeEvidenceId]);

  useEffect(() => {
    setQuestions((current) => [
      ...initialQuestions,
      ...current.filter(
        (question) => !initialQuestions.some((incoming) => incoming.id === question.id),
      ),
    ]);
  }, [initialQuestions]);

  useEffect(() => {
    setEvidence((current) => ({ ...current, ...initialEvidence }));
  }, [initialEvidence]);

  const activeQuestion = useMemo((): DeskQuestion | null => {
    const selected = questions.find((question) => question.id === activeId);
    if (selected !== undefined) return selected;
    return questions.at(0) ?? null;
  }, [activeId, questions]);
  const activeEvidence = activeEvidenceId ? (evidence[activeEvidenceId] ?? null) : null;

  const inspectEvidence = (evidenceId: string, trigger: HTMLElement) => {
    lastTriggerRef.current = trigger;
    setActiveEvidenceId((current) => (current === evidenceId ? null : evidenceId));
  };

  const selectQuestion = (id: string) => {
    setActiveId(id);
    setActiveEvidenceId(null);
    setComposerError(null);
  };

  const submitQuestion = async (event: FormSubmitEvent) => {
    event.preventDefault();
    const trimmed = questionText.trim();
    if (
      trimmed.length < 3 ||
      processingTitle !== null ||
      readyFiles === 0 ||
      onAsk === undefined
    ) {
      return;
    }
    setComposerError(null);
    setAnnouncement("Looking through your sources and checking the evidence.");
    setProcessingTitle(trimmed);
    setActiveEvidenceId(null);
    try {
      const result = await onAsk(trimmed);
      const adapted: DeskResultSet = adaptQuestionResults([result]);
      const generated = adapted.questions.at(0);
      if (generated === undefined) throw new Error("empty_result");
      setQuestions((current) => [
        generated,
        ...current.filter((item) => item.id !== generated.id),
      ]);
      setEvidence((current) => ({ ...current, ...adapted.evidence }));
      setActiveId(generated.id);
      setAnnouncement(`${generated.stateLabel}.`);
      setQuestionText("");
    } catch (error) {
      const code = apiErrorCode(error);
      setComposerError(
        code === "authentication_required"
          ? "The Google connection expired. Reconnect Drive before asking again."
          : code === "workspace_not_ready"
            ? "Extent is still reading the folder. Wait for a readable file, then try again."
            : code === "rate_limited"
              ? "Too many questions were sent in a short time. Wait a moment, then try again."
              : code === "request_timed_out"
                ? "This question took too long. Your text is still here, so you can try again."
                : code === "retrieval_unavailable" || code === "rate_limit_unavailable"
                  ? "Extent couldn’t look through the files right now. Your text is still here, so you can try again."
                  : "Extent couldn’t finish this question. Your text is still here, so you can try again.",
      );
      setAnnouncement("Question not completed. Your text is still here.");
    } finally {
      setProcessingTitle(null);
    }
  };

  const closeEvidence = () => {
    setActiveEvidenceId(null);
    window.setTimeout(() => lastTriggerRef.current?.focus(), 0);
  };

  const openCoverage = () => coverageDialogRef.current?.showModal();

  return (
    <div className={`workspace workspace--${mode}`}>
      <WorkspaceHeader
        coverageLabel={coverageLabel}
        folderTitle={folderTitle}
        mode={mode}
        onCoverage={openCoverage}
      />

      <div
        className={`workspace__body${activeEvidence ? " workspace__body--evidence" : ""}`}
      >
        <QuestionHistory
          activeId={activeQuestion?.id ?? null}
          onSelect={selectQuestion}
          questions={questions}
        />

        <main className="workspace__main" id="main-content">
          <details className="mobile-history">
            <summary>
              <span>Questions</span>
              <span>{activeQuestion?.shortTitle ?? "No questions yet"}</span>
            </summary>
            <QuestionHistoryList
              activeId={activeQuestion?.id ?? null}
              onSelect={selectQuestion}
              questions={questions}
            />
          </details>

          <div className="workspace__result-scroll">
            <div className="workspace__result">
              {refreshError ? (
                <div className="message message--warning workspace-notice" role="status">
                  <p>{refreshError}</p>
                  {onRefresh ? (
                    <button className="text-button" onClick={onRefresh} type="button">
                      Try again
                    </button>
                  ) : null}
                </div>
              ) : null}
              {mode === "sample" ? (
                <div className="sample-disclosure">
                  <strong>Prepared fictional sample</strong>
                  <span>Not connected to Google Drive</span>
                </div>
              ) : null}
              {processingTitle ? (
                <ProcessingState
                  title={processingTitle}
                  unavailableFiles={totalFiles - readyFiles}
                />
              ) : activeQuestion ? (
                <QuestionView
                  activeEvidenceId={activeEvidenceId}
                  onInspect={inspectEvidence}
                  onReviewCoverage={openCoverage}
                  question={activeQuestion}
                />
              ) : (
                <EmptyQuestionState readyFiles={readyFiles} />
              )}
            </div>
          </div>

          {mode === "sample" ? (
            <SampleComposer />
          ) : (
            <Composer
              error={composerError}
              inputRef={inputRef}
              onChange={(value) => {
                setQuestionText(value);
                setComposerError(null);
              }}
              onSubmit={(event) => void submitQuestion(event)}
              processing={processingTitle !== null}
              question={questionText}
              readyFiles={readyFiles}
            />
          )}
          <p aria-live="polite" className="visually-hidden" role="status">
            {announcement}
          </p>
        </main>

        {activeEvidence ? (
          <EvidencePanel
            evidence={activeEvidence}
            onClose={closeEvidence}
            panelRef={evidencePanelRef}
          />
        ) : null}
      </div>

      <CoverageDialog
        dialogRef={coverageDialogRef}
        files={files}
        mode={mode}
        readyFiles={readyFiles}
        totalFiles={totalFiles}
      />
    </div>
  );
}

function WorkspaceHeader({
  coverageLabel,
  folderTitle,
  mode,
  onCoverage,
}: {
  coverageLabel: string;
  folderTitle: string;
  mode: WorkspaceMode;
  onCoverage: () => void;
}) {
  return (
    <header className="workspace-header">
      <div className="workspace-header__brand">
        <Wordmark />
        <span aria-hidden="true">·</span>
        <span>{folderTitle}</span>
      </div>
      <div className="workspace-header__status">
        <button
          aria-label={`Review files. ${coverageLabel}`}
          className="coverage-trigger"
          onClick={onCoverage}
          type="button"
        >
          <span>{coverageLabel}</span>
        </button>
        <span>
          {mode === "sample" ? "Prepared fictional sample" : "Drive connected · read-only"}
        </span>
      </div>
    </header>
  );
}

function QuestionHistory({
  activeId,
  onSelect,
  questions,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
  questions: readonly DeskQuestion[];
}) {
  return (
    <nav aria-label="Questions" className="question-history">
      <h2>Questions</h2>
      <QuestionHistoryList activeId={activeId} onSelect={onSelect} questions={questions} />
    </nav>
  );
}

function QuestionHistoryList({
  activeId,
  onSelect,
  questions,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
  questions: readonly DeskQuestion[];
}) {
  return (
    <div className="question-history__list">
      {questions.map((question) => (
        <button
          aria-current={question.id === activeId ? "page" : undefined}
          className="history-item"
          key={question.id}
          onClick={() => {
            onSelect(question.id);
          }}
          type="button"
        >
          <span>{question.shortTitle}</span>
          <small className={`result-tone result-tone--${question.kind}`}>
            {question.stateLabel}
          </small>
        </button>
      ))}
      {questions.length === 0 ? (
        <p className="question-history__empty">Your questions will appear here.</p>
      ) : null}
    </div>
  );
}

function ProcessingState({
  title,
  unavailableFiles,
}: {
  title: string;
  unavailableFiles: number;
}) {
  return (
    <div aria-live="polite" className="processing-state">
      <h1>{title}</h1>
      <p className="busy-line">
        <span aria-hidden="true" className="busy-dot" />
        Looking through your sources and checking the evidence
      </p>
      {unavailableFiles > 0 ? (
        <p>
          {formatCount(unavailableFiles, "unavailable file")} will not be checked. The
          result will say when this prevents a firm answer.
        </p>
      ) : null}
    </div>
  );
}

function EmptyQuestionState({ readyFiles }: { readyFiles: number }) {
  return (
    <div className="empty-question-state">
      <h1>What do you want to find out?</h1>
      <p>
        {readyFiles > 0
          ? "Extent looks through the files that are ready and shows only findings tied to exact source text."
          : "Extent needs at least one readable file before you can ask a question."}
      </p>
    </div>
  );
}

function QuestionView({
  activeEvidenceId,
  onInspect,
  onReviewCoverage,
  question,
}: {
  activeEvidenceId: string | null;
  onInspect: (evidenceId: string, trigger: HTMLElement) => void;
  onReviewCoverage: () => void;
  question: DeskQuestion;
}) {
  return (
    <article className="question-result">
      <header className="question-result__header">
        <h1>{question.title}</h1>
        <p className={`result-state result-tone result-tone--${question.kind}`}>
          {question.stateLabel}
        </p>
      </header>

      <p className="finding-copy">{question.finding}</p>

      {question.evidenceRows ? (
        <EvidenceRows
          activeEvidenceId={activeEvidenceId}
          heading={
            question.stateLabel === "Values extracted" ||
            question.stateLabel === "Partial extraction"
              ? "Where Extent found it"
              : "Why Extent says this"
          }
          onInspect={onInspect}
          rows={question.evidenceRows}
        />
      ) : null}

      {question.kind === "disagree" && question.comparisons ? (
        <ComparisonView
          activeEvidenceId={activeEvidenceId}
          comparisons={question.comparisons}
          onInspect={onInspect}
        />
      ) : null}

      {question.kind === "change" && question.timeline ? (
        <TimelineView
          activeEvidenceId={activeEvidenceId}
          onInspect={onInspect}
          timeline={question.timeline}
        />
      ) : null}

      {question.unavailable ? (
        <UnavailableFiles
          files={question.unavailable}
          note={question.unavailableNote ?? "These files were not available to check."}
        />
      ) : null}

      {question.passages ? (
        <EvidenceRows
          activeEvidenceId={activeEvidenceId}
          heading={question.passagesHeading ?? "Relevant passages"}
          onInspect={onInspect}
          passageStyle
          rows={question.passages}
        />
      ) : null}

      {question.passagesNote ? (
        <p className="result-note">{question.passagesNote}</p>
      ) : null}
      {question.note ? <p className="result-note">{question.note}</p> : null}
      {question.coverage ? (
        <p className="side-note question-result__coverage">
          {question.coverage}{" "}
          <button className="inline-button" onClick={onReviewCoverage} type="button">
            {question.kind === "incomplete" ? "Review unavailable files" : "Review files"}
          </button>
        </p>
      ) : null}
    </article>
  );
}

function EvidenceRows({
  activeEvidenceId,
  heading,
  onInspect,
  passageStyle = false,
  rows,
}: {
  activeEvidenceId: string | null;
  heading: string;
  onInspect: (evidenceId: string, trigger: HTMLElement) => void;
  passageStyle?: boolean;
  rows: readonly { evidenceId: string; label: string; locator: string }[];
}) {
  return (
    <section className="evidence-rows" aria-label={heading}>
      <h2>{heading}</h2>
      {rows.map((row) => {
        const active = activeEvidenceId === row.evidenceId;
        return (
          <button
            aria-expanded={active}
            className={`evidence-row${active ? " evidence-row--active" : ""}${passageStyle ? " evidence-row--passage" : ""}`}
            key={row.evidenceId}
            onClick={(event) => {
              onInspect(row.evidenceId, event.currentTarget);
            }}
            type="button"
          >
            <span>
              <strong>{passageStyle ? `“${row.label}”` : row.label}</strong>
              <small>{row.locator}</small>
            </span>
            <span>
              {active ? "viewing →" : passageStyle ? "view passage" : "view evidence"}
            </span>
          </button>
        );
      })}
    </section>
  );
}

function ComparisonView({
  activeEvidenceId,
  comparisons,
  onInspect,
}: {
  activeEvidenceId: string | null;
  comparisons: NonNullable<DeskQuestion["comparisons"]>;
  onInspect: (evidenceId: string, trigger: HTMLElement) => void;
}) {
  return (
    <div className="comparison-grid">
      {comparisons.map((comparison) => {
        const active = activeEvidenceId === comparison.evidenceId;
        return (
          <section key={comparison.evidenceId}>
            <strong className="comparison-grid__value">{comparison.value}</strong>
            <p>{comparison.caption}</p>
            <button
              className="comparison-grid__inspect"
              onClick={(event) => {
                onInspect(comparison.evidenceId, event.currentTarget);
              }}
              type="button"
            >
              <span>{comparison.locator} · </span>
              <strong>{active ? "viewing →" : "view evidence"}</strong>
            </button>
          </section>
        );
      })}
    </div>
  );
}

function TimelineView({
  activeEvidenceId,
  onInspect,
  timeline,
}: {
  activeEvidenceId: string | null;
  onInspect: (evidenceId: string, trigger: HTMLElement) => void;
  timeline: NonNullable<DeskQuestion["timeline"]>;
}) {
  return (
    <div className="timeline">
      {timeline.map((item, index) => {
        const active = activeEvidenceId === item.evidenceId;
        return (
          <div className="timeline__item" key={item.evidenceId}>
            <div className="timeline__rail" aria-hidden="true">
              <span
                className={
                  index === timeline.length - 1
                    ? "timeline__dot timeline__dot--current"
                    : "timeline__dot"
                }
              />
              {index < timeline.length - 1 ? <span className="timeline__line" /> : null}
            </div>
            <div className="timeline__content">
              <p>{item.when}</p>
              <div>
                <strong>{item.value}</strong>
                <span>{item.caption}</span>
              </div>
              <button
                onClick={(event) => {
                  onInspect(item.evidenceId, event.currentTarget);
                }}
                type="button"
              >
                <span>{item.locator} · </span>
                <strong>{active ? "viewing →" : "view evidence"}</strong>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function UnavailableFiles({
  files,
  note,
}: {
  files: readonly { name: string; reason: string }[];
  note: string;
}) {
  return (
    <section className="unavailable-files" aria-labelledby="unavailable-title">
      <h2 id="unavailable-title">Files not checked</h2>
      {files.map((file) => (
        <div key={file.name}>
          <span>{file.name}</span>
          <span>{file.reason}</span>
        </div>
      ))}
      <p>{note}</p>
    </section>
  );
}

function Composer({
  error,
  inputRef,
  onChange,
  onSubmit,
  processing,
  question,
  readyFiles,
}: {
  error: string | null;
  inputRef: RefObject<HTMLInputElement | null>;
  onChange: (value: string) => void;
  onSubmit: (event: FormSubmitEvent) => void;
  processing: boolean;
  question: string;
  readyFiles: number;
}) {
  return (
    <div className="composer-wrap">
      <form aria-busy={processing} className="composer" onSubmit={onSubmit}>
        <label className="visually-hidden" htmlFor="workspace-question">
          Question about this folder
        </label>
        <input
          aria-describedby={error ? "composer-error" : undefined}
          aria-invalid={error ? true : undefined}
          disabled={readyFiles === 0}
          id="workspace-question"
          maxLength={2_000}
          onChange={(event) => {
            onChange(event.target.value);
          }}
          placeholder={
            readyFiles > 0
              ? "What is the total premium for the complete package?"
              : "Extent needs at least one readable file before you can ask a question."
          }
          ref={inputRef}
          type="text"
          value={question}
        />
        <button
          aria-label={processing ? "Looking through your sources" : "Ask about these files"}
          className="button button--primary button--compact"
          disabled={readyFiles === 0 || processing || question.trim().length < 3}
          type="submit"
        >
          {processing ? "Looking…" : "Ask"}
        </button>
      </form>
      {error ? (
        <p className="composer-error" id="composer-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function SampleComposer() {
  return (
    <div className="composer-wrap">
      <div className="composer sample-composer">
        <p>
          This is a fixed, prepared result. Connect Google Drive to ask questions about your
          own folder.
        </p>
        <Link className="button button--primary button--compact" href="/connect">
          Connect Google Drive
        </Link>
      </div>
    </div>
  );
}

function EvidencePanel({
  evidence,
  onClose,
  panelRef,
}: {
  evidence: DeskEvidence;
  onClose: () => void;
  panelRef: RefObject<HTMLElement | null>;
}) {
  const driveHref = evidence.driveFileId
    ? `https://drive.google.com/open?id=${encodeURIComponent(evidence.driveFileId)}`
    : null;
  return (
    <aside
      aria-label="Why Extent says this"
      className="evidence-panel"
      ref={panelRef}
      tabIndex={-1}
    >
      <header>
        <h2>Why Extent says this</h2>
        <button aria-label="Close evidence" onClick={onClose} type="button">
          esc · close ✕
        </button>
      </header>
      <div className="evidence-panel__body">
        <p className="evidence-panel__context">{evidence.context}</p>
        <article className="quote-card">
          <div className="quote-card__bar">
            <span>{evidence.file}</span>
            <span>{evidence.locator}</span>
          </div>
          <blockquote>
            {evidence.pre}
            <mark>{evidence.highlight}</mark>
            {evidence.post}
          </blockquote>
          <div className="quote-card__footer">
            <span>Exact quote</span>
            {driveHref ? (
              <a href={driveHref} rel="noreferrer" target="_blank">
                Open in Drive ↗
              </a>
            ) : (
              <span>Prepared file</span>
            )}
          </div>
        </article>

        {evidence.ocr ? (
          <p className="ocr-note">
            This text was read by OCR from a scanned file. Verify it against the original in
            Drive before relying on it.
          </p>
        ) : null}

        <dl className="evidence-meta">
          {evidence.meta.map((item) => (
            <div key={`${item.label}:${item.value}`}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>

        <p className="evidence-caveat">
          A citation means the source contains these words. It does not mean the value is
          current, complete, or controlling. Which document governs is your call.
        </p>
        <details className="technical-details">
          <summary>Technical checks</summary>
          <p>
            Extent kept this quote with its file and page or line location before showing
            the finding.
          </p>
        </details>
      </div>
    </aside>
  );
}

function CoverageDialog({
  dialogRef,
  files,
  mode,
  readyFiles,
  totalFiles,
}: {
  dialogRef: RefObject<HTMLDialogElement | null>;
  files: readonly DeskFile[];
  mode: WorkspaceMode;
  readyFiles: number;
  totalFiles: number;
}) {
  const unavailable = Math.max(0, totalFiles - readyFiles);
  const close = () => dialogRef.current?.close();
  return (
    <dialog
      className="coverage-dialog"
      onClick={(event) => {
        if (event.currentTarget === event.target) close();
      }}
      ref={dialogRef}
    >
      <div className="coverage-dialog__surface">
        <header>
          <div>
            <h2>{mode === "sample" ? "Files in this sample" : "Files in this folder"}</h2>
            <p>{formatCoverageSummary(totalFiles, readyFiles, unavailable)}</p>
          </div>
          <button aria-label="Close file list" onClick={close} type="button">
            esc · close ✕
          </button>
        </header>
        <div className="coverage-dialog__list">
          {files.map((file, index) => (
            <div key={file.id ?? `${file.folder}:${file.name}:${String(index)}`}>
              <span>
                {file.name}
                <small> · {file.folder}</small>
              </span>
              <span className={`file-state file-state--${file.tone}`}>{file.state}</span>
            </div>
          ))}
          {unavailable > 0 ? (
            <p>
              Unavailable files stay listed here. They may contain relevant evidence, and a
              result will say when this prevents a firm answer.
            </p>
          ) : (
            <p>Every listed file was available to check.</p>
          )}
        </div>
      </div>
    </dialog>
  );
}
