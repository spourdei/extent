# Deployment topology

Extent uses one application topology in development and production:

```text
Browser -> Vercel Next.js -> Render FastAPI -> Render Postgres/pgvector
                                      |      -> Render Key Value
                                      `-> RQ enqueue
Render RQ worker ----------------------------^
```

FastAPI and the RQ worker run as separate Dockerized Render services from the same Python package
and checked-in image definition. The API runs Alembic before starting Uvicorn. The shared image
provides the Tesseract executable and English language data required by worker startup.
Postgres is the durable product-state authority; Redis is delivery infrastructure and may not be
used as the only record of a product operation. Alembic migrations run once as an explicit
API-start boundary before Uvicorn starts.

The repository defines and checks these boundaries locally. A public Vercel-to-Render proxy,
session-cookie, migration-revision, API, and worker smoke remains required before the topology can
be described as deployed.

## Render environment

The root `render.yaml` creates the API, worker, Postgres database, Key Value instance, and a shared
runtime group. Render prompts for the OAuth, provider, and encryption secrets during the first
Blueprint import. Configure the two provider base URLs manually in that shared group so the
endpoint remains deployment configuration instead of source-controlled vendor configuration. The
Vercel origin is fixed to `https://extent-web.vercel.app`.

Configure these server-only values on both services where applicable:

- `EXTENT_ENVIRONMENT=production`
- `EXTENT_DATABASE_URL`: Render Postgres internal URL; the settings boundary normalizes it from
  `postgresql://` to `postgresql+psycopg://`
- `EXTENT_REDIS_URL`: Render Key Value internal URL
- `EXTENT_QUEUE_NAME=extent`
- `EXTENT_ALLOWED_HOSTS`: the exact Render API service hostname, without a scheme, port, or
  wildcard
- `EXTENT_ALLOWED_ORIGINS`: the deployed Vercel origin
- `EXTENT_PUBLIC_WEB_ORIGIN`: the deployed Vercel origin; Google must register
  `<origin>/api/backend/v1/auth/google/callback`
- `EXTENT_GOOGLE_CLIENT_ID` and `EXTENT_GOOGLE_CLIENT_SECRET`: Google web-client values
- `EXTENT_CREDENTIAL_ENCRYPTION_KEYS`: newest-first versioned AEAD keys; configure the same value
  on the API and worker
- `EXTENT_MODEL_API_KEY`: server-only answer-model credential
- `EXTENT_MODEL_BASE_URL`: the HTTPS root of the selected OpenAI-compatible API; configure it in
  the shared Render environment group
- `EXTENT_MODEL_NAME=gemini-3.5-flash`
- `EXTENT_MODEL_TIMEOUT_SECONDS=90`
- `EXTENT_EMBEDDING_API_KEY`: server-only embedding credential; production refuses to start
  without it
- `EXTENT_EMBEDDING_BASE_URL`: the HTTPS root of the selected OpenAI-compatible API; configure it
  in the shared Render environment group
- `EXTENT_EMBEDDING_MODEL=text-embedding-3-large`: the provider must honor OpenAI's
  `dimensions` parameter; Extent requests and validates exactly 1,536 values
- `EXTENT_QUERY_REQUESTS_PER_MINUTE=12`: atomic per-user question admission before provider
  work
- `EXTENT_MAX_SOURCE_BYTES=25000000`: per-source download and parsing boundary; keep the same
  value on the API and worker
- `EXTENT_OCR_EXECUTABLE=tesseract`: worker-local OCR executable; worker startup fails when it
  is unavailable

Runtime startup validates this capability set as one boundary. OAuth credentials, the
credential keyring, answer-model key, embedding key, non-loopback database and Redis URLs, and an
exact HTTPS web/CORS origin must all be present before the API and worker can report healthy. The
ASGI edge also rejects Host headers outside the exact configured Render hostname allowlist.
POST, PUT, and PATCH bodies are capped at 16 KiB while they are received, before JSON allocation,
authentication, queue access, or provider work; declared and chunked oversize requests return 413.
The separate Alembic release action validates its database URL but does not require runtime
provider credentials.

The adapters do not select a provider. A direct Gemini OpenAI-compatible endpoint remains a
supported configuration when its base URL, API key, and compatible model names are supplied, but
the production Blueprint does not hard-code or default to that endpoint.

The API start command is:

```bash
.venv/bin/python -m extent_api.render_web
```

The worker start command is:

```bash
.venv/bin/python -m extent_api.worker
```

The release migration command is:

```bash
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
```

The Vercel project receives only `EXTENT_API_INTERNAL_URL` and
`EXTENT_API_PROXY_TARGET`; both are the origin-only HTTPS URL for the Render API. A Vercel
production build fails instead of falling back to localhost when the proxy target is absent or
unsafe, and server-side sample reads reject an absent or unsafe internal URL in that environment.
Database and Redis credentials never enter the browser or Next.js public environment.

## OAuth diagnostics

FastAPI assigns every request a validated `X-Request-Id`. Each admitted request emits one JSON
completion event containing only its request ID, method, route template, status, and duration;
unhandled failures add only the exception class. Each claimed ingestion attempt emits one JSON
completion event with its run ID, bounded outcome, duration, and exception class when applicable.
Expected OAuth failures emit one JSON line with `event`, `request_id`, `stage`, and a bounded
`reason` code. The connect
surface shows the same request ID as a diagnostic reference so an operator can correlate the
browser outcome with API logs.

OAuth callback access logs replace the full query with `?[redacted]`. Authorization codes,
state values, tokens, client secrets, provider response bodies, and provider error descriptions
must never be logged. Request bodies, question text, document excerpts, route parameters, and
query strings are likewise excluded from application event payloads. Safe reason codes distinguish failures such as `invalid_client`,
`invalid_grant`, `network_error`, `required_scopes_missing`, `id_token_invalid`, and
`account_persistence_failed` without reproducing sensitive provider data.
