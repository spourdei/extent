# Architecture

Extent is a React application backed by one FastAPI service.

## Runtime boundary

- `apps/web` owns rendering, route states, accessibility, and the server-side HTTP adapter used by React Server Components.
- `apps/api` owns authentication, Google Drive access, ingestion, retrieval, answer generation, evidence validation, and persistence.
- The active authenticated slice persists a workspace/run/progress turn as `enqueue_pending`
  before enqueueing one deterministic RQ `sync_folder` job. The job performs capped recursive
  Drive discovery, then commits the source manifest, admission, download, parsed artifacts,
  embedding work, and readiness as separate durable stages. Page- and line-addressed source processing
  preserves retryable, deterministic, unsupported, and inaccessible outcomes while
  projecting the internal stages into the owner-scoped polling contract.
- The web application does not import backend domain services or provider SDKs. It consumes bounded JSON read models over HTTP.
- Pydantic models and the generated OpenAPI document are the API contract authority. The web application still validates every response at runtime before rendering it.

The sample experience follows the same boundary as the eventual live product. FastAPI serves the deterministic projection; Next.js fetches it and fails closed if transport or validation fails. This keeps the demo useful during incremental delivery without maintaining a second JavaScript backend.

## Request path

```text
Browser -> Next.js / React -> FastAPI -> domain services -> providers and persistence
                              |
                              +-> bounded, citation-ready read models
```

Browser-facing API and OAuth traffic should be routed through the application origin in production. Server Components use the private FastAPI service URL. A public `NEXT_PUBLIC_*` backend origin is deliberately avoided so credentials, cookie policy, CORS, and the content-security policy have one controlled boundary.

Google redirects through `/api/backend/v1/auth/google/callback` on the Next.js origin and is
rewritten to FastAPI. FastAPI stores one-use state and encrypted PKCE server-side, verifies the
Google identity and required scopes, encrypts refresh credentials, and sets an opaque hashed
session. Next.js never handles authorization codes or provider tokens.

## Contract rules

- API field names are camelCase on the wire even when Python uses snake_case internally.
- Public response models reject unexpected fields and place explicit bounds on collections and text.
- Expected domain outcomes such as no evidence or unsupported files are typed successful responses. Authentication, rate-limit, provider, and transport failures use appropriate non-2xx responses.
- Raw model output, source text, credentials, and provider payloads are never sent directly to the interface.
- Citations are published only after their source version and locator have been revalidated.

## Repository transition

The superseded TypeScript backend and handwritten contract packages have been deleted. Pydantic,
the checked-in OpenAPI document, and the generated TypeScript client own the cross-language
contract. Focused browser validators fail closed at each consumed HTTP boundary; provider access,
persistence, orchestration, and publication decisions belong exclusively to FastAPI.

## Local development

Run the services in separate terminals:

```bash
pnpm dev:web
pnpm dev:api
```

The web server reads `EXTENT_API_INTERNAL_URL`, which defaults to `http://127.0.0.1:8000` for local development.
