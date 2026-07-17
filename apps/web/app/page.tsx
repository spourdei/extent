import Link from "next/link";

import { ProductHeader } from "../components/product-header";
import { adaptSampleWorkspace } from "../lib/sample-model";
import { getSyntheticPreviewData } from "../src/server/sample-query-service";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function HomePage() {
  const sample = adaptSampleWorkspace(await getSyntheticPreviewData());
  const sampleQuestion = sample.questions.at(0);
  const evidenceRow = sampleQuestion?.evidenceRows?.at(0);
  const sampleEvidence = evidenceRow ? sample.evidence[evidenceRow.evidenceId] : undefined;
  if (
    sampleQuestion === undefined ||
    evidenceRow === undefined ||
    sampleEvidence === undefined
  ) {
    throw new Error("The prepared sample preview did not contain inspectable evidence.");
  }

  return (
    <div className="public-page">
      <ProductHeader
        action={
          <Link className="header-link" href="/connect">
            Connect Google Drive
          </Link>
        }
      />

      <main className="intro" id="main-content">
        <div className="intro__inner">
          <section className="intro__hero" aria-labelledby="intro-title">
            <h1 id="intro-title">
              Ask a question across a folder. Check the exact quote behind each finding.
            </h1>
            <p>
              Connect Google Drive and ask about the files in one folder. Extent gives you a
              small set of findings with exact quotes, and tells you when documents disagree
              or a file could not be checked.
            </p>
            <div className="intro__actions">
              <Link className="button button--primary" href="/sample">
                Try the sample
              </Link>
              <Link className="text-link" href="/connect">
                Connect Google Drive
              </Link>
            </div>
            <p className="intro__disclosure">
              The sample uses a prepared set of fictional documents. No sign-in or Drive
              access is needed.
            </p>
          </section>

          <section
            className="intro__proof"
            aria-label="Example finding and source evidence"
          >
            <div className="intro__finding">
              <p className="micro-label">Prepared fictional sample</p>
              <h2>{sampleQuestion.title}</h2>
              <p className="status-text status-text--success">
                {sampleQuestion.stateLabel}
              </p>
              <p className="intro__finding-copy">{sampleQuestion.finding}</p>
              <p className="side-note">{sampleQuestion.coverage}</p>
            </div>

            <div className="intro__evidence">
              <p className="micro-label">The evidence behind this finding</p>
              <article className="quote-card">
                <div className="quote-card__bar">
                  <span>{sampleEvidence.file}</span>
                  <span>{sampleEvidence.locator}</span>
                </div>
                <blockquote>
                  {sampleEvidence.pre}
                  <mark>{sampleEvidence.highlight}</mark>
                  {sampleEvidence.post}
                </blockquote>
                <div className="quote-card__footer">
                  <span>Exact quote</span>
                  <Link href="/sample">View the evidence ↗</Link>
                </div>
              </article>
              <p className="intro__evidence-note">
                A citation means the source contains these words. It does not mean the value
                is current or controlling. Which document governs is your call.
              </p>
            </div>
          </section>

          <section className="intro__state-list" aria-label="How Extent reports results">
            <div>
              <h3>Sources disagree</h3>
              <p>
                You see both supported values side by side, each with its own quote and
                source. Extent does not choose between them unless the documents establish
                an order.
              </p>
            </div>
            <div>
              <h3>A newer value is not always a disagreement</h3>
              <p>
                When the documents establish an order, Extent shows what changed. When they
                do not, both values stay visible for review.
              </p>
            </div>
            <div>
              <h3>Limits stay visible</h3>
              <p>
                See when a file could not be checked and why that prevents a firm
                conclusion.
              </p>
            </div>
            <div>
              <h3>No evidence found is not the same as an incomplete folder</h3>
              <p>
                Extent says whether it checked every available file or whether an
                unavailable file could still contain relevant evidence.
              </p>
            </div>
          </section>

          <p className="intro__privacy">
            Read-only Drive access. The folder link sets what Extent can read. The account
            you connect still controls which files Extent can open. Google credentials and
            document text are not stored in this browser.
          </p>
        </div>
      </main>
    </div>
  );
}
