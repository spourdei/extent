# Extent API

FastAPI is the sole backend authority. It owns Google OAuth, opaque browser sessions, encrypted
refresh credentials, the checked-in synthetic endpoints, authenticated workspace creation, and
every Drive/query operation.

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e apps/api
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python apps/api/scripts/export_openapi.py --check
.venv/bin/python -m pytest apps/api/tests
.venv/bin/uvicorn extent_api.main:app --reload --reload-dir apps/api/src --app-dir apps/api/src
```

Local API documentation is available at `http://127.0.0.1:8000/api/docs`.

`EXTENT_DATABASE_URL` uses psycopg 3. The settings boundary accepts Render's native
`postgresql://` connection string and normalizes it to `postgresql+psycopg://`; all other drivers
fail closed. Render Postgres with pgvector is the deployed database, and Render Key Value is the
deployed Redis service. FastAPI, SQLAlchemy, and Alembic remain the application and schema
authorities. `EXTENT_REDIS_URL` accepts `redis://` and `rediss://`, and both database and Redis
credentials remain server-only.

Google OAuth uses the maintained Google Python libraries with state, PKCE, offline access, and
the read-only Drive scope. Register
`http://localhost:3000/api/backend/v1/auth/google/callback` as the local Google web-client
redirect, then configure the three server-only values documented in `.env.example`. The browser
receives only an opaque `HttpOnly`, `SameSite=Lax` session cookie. Google access, refresh, and ID
tokens are never returned through OpenAPI or stored in browser-accessible storage.

`POST /api/v1/workspaces` accepts a strict Drive folder locator and atomically persists the
owner-scoped workspace, ingestion run, and initial progress message before enqueueing the one
`sync_folder(run_id)` RQ job. The worker uses the encrypted server-held refresh credential with
the maintained Drive v3 client, recursively traverses within the disclosed caps, and commits a
discovered source manifest before admitting supported files. It then commits download, parsed
artifacts, embedding, and ready transitions while projecting them into the bounded public
queued, parsing, ready, failed, unsupported, and capped states. It extracts embedded PDF text and
falls back to local, page-aware Tesseract OCR for image-only PDFs, exports Google Docs to plain
text, parses comma-separated UTF-8 CSV rows, extracts DOCX body paragraphs and tables, parses
bounded XLSX worksheets, and downloads plain text or Markdown without an application-level
file-size limit. PDF page count is also uncapped for scalability testing. DOCX `document.xml` is
capped at 20,000,000 uncompressed bytes to bound ZIP/XML parser memory. XLSX archives are capped
at 20 sheets, 10,000 rows per sheet, 200 columns, and 50,000,000 total uncompressed bytes. CSV and
XLSX rows remain searchable, while deterministic
complete-list extraction marks undivided header grids ambiguous instead of guessing that the
first row defines columns. The worker
still persists at most 1,500 evidence blocks across one ingestion run. It persists hashed page- or line-relative evidence
blocks without retaining the downloaded file. Each new block records the raw source hash, its separate
normalized-text hash, and an explicit parser pipeline version; the four-part source, raw hash,
pipeline, and ordinal key prevents duplicate artifact rows. OCR-derived sources use a distinct
pipeline identity so the public workspace can disclose recognition provenance. Blank, encrypted,
malformed, structurally excessive, or inaccessible sources become visible failed
states. When `EXTENT_EMBEDDING_API_KEY` is configured, the worker also persists fixed-size
embeddings before each source becomes ready; transient provider failures are stored separately
from deterministic source failures, and every new failure records whether it occurred during
admission, download, parse, or embedding. Retryable failures leave the run recoverable instead of
admitting an incomplete vector index. Terminal run status is derived from the manifest: all-ready is ready, mixed ready
and coverage gaps is partial, and a resolved manifest with no ready source is failed.
`GET /api/v1/workspaces/{id}` is the
private polling projection; an opaque UUID never
bypasses its user ownership check. `POST /api/v1/workspaces/{id}/retry` atomically admits only an
owner-scoped retryable run, commits it as `enqueue_pending`, and reuses its deterministic queue
identity. Successful handoff advances the run to `queued`; a worker may claim the pending state
directly if it starts first. Duplicate requests that observe active work converge, while an
enqueue failure restores `retryable` only if no worker has already claimed the run.
Published `ready`, `partial`, and `failed` runs are immutable: late worker recovery cannot
reclassify them or clear their finish time, and newly supported formats require a new workspace
ingestion instead of reopening a published manifest.
New runs persist `drive-ingestion-v1` plus an execution-attempt count that advances only when a
worker claims discovery. Legacy rows keep null execution identity because their exact historical
attempt count and workflow version cannot be reconstructed safely.
Known runs allow the initial execution plus two retries. If the third execution still fails,
remaining mutable sources become terminal failures in the same transaction, already-ready
evidence is preserved, and the manifest publishes `partial` or `failed` instead of another retry.

`POST /api/v1/workspaces/{id}/messages` retrieves a bounded, owner-scoped evidence set. With a
separately configured embedding key it embeds the question and ranks prepared blocks by cosine
distance; without that key it uses explicit lexical retrieval even when answer generation is
configured. Before either path, an atomic Redis counter admits at most the configured number of
question attempts per authenticated user and UTC minute; excess traffic returns 429 with a
bounded `Retry-After`, while a limiter outage fails closed before provider work. An embedding
outage returns a retryable 503 and never silently changes retrieval modes. Explicit all/every
list requests for one named field branch before history, embedding, retrieval ranking, and model
work. `exhaustive-extraction-policy-v1` derives the target label from the question, scans every
ready block in stable source order, and evaluates domain-neutral explicit label/value structures
with exact-offset citations. Manifest gaps or structurally ambiguous matching passages make the
result partial; more than 200 distinct rows fail visibly instead of being truncated. The legacy
premium policy literal remains readable only so persisted history continues to project safely.
Ambiguous field requests use `clarification-policy-v1`, publish no claims, and do not report a
search that never ran.
Ordinary lexical retrieval does not synthesize agent-noun labels from arbitrary verbs. Verbal
questions require literal or semantic narrative evidence and abstain when no such evidence is
available rather than promoting a scoped assignment as the requested field.
All other questions call the server-only OpenAI-compatible answer model and validate its response
as a structured draft. The answer provider never publishes directly: exact quotes, source/run
ownership, numeric and date literals, and comparison branches must pass `publication-policy-v1`
before claims and citations are persisted. Provider failures after retrieval fall back to
evidence-only output.

Migrations are an explicit release action: FastAPI startup never creates or changes tables.
Run `pnpm migrate:check` without a database to verify the single migration head. For a Render
release, run `pnpm migrate` once, then verify the deployed `alembic_version` equals the repository
head. Run the API and RQ worker as separate native processes from the same Python package. Do not
expose database or Redis credentials to Next.js/browser code.

## Evaluations

`pnpm eval:check` runs the twelve-case frozen publication-policy regression and verifies that the
checked-in report has not drifted. `pnpm eval:openai:validate` validates the twelve-case system
casebook and its golden source corpus without making provider requests. Both run in `pnpm check`.

`pnpm eval:live` is an opt-in provider smoke that loads credentials only through `Settings()` and
makes live answer-model and embedding requests. `pnpm eval:openai` is the separate authenticated
end-to-end system suite; it exercises the real workspace question endpoint and may make paid
provider requests. See [`evals/openai/README.md`](evals/openai/README.md) before running it.
