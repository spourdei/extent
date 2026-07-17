# Public Engineering Rules

- Run `pnpm check` before handing off a coherent change. It covers formatting, linting, type checking, focused unit tests, migration and OpenAPI drift, and the production web build for the active React/FastAPI system.
- FastAPI is the sole backend authority. Network and provider SDK imports belong only in `apps/api` adapter modules; `apps/web` communicates with it over HTTP.
- Pydantic models and OpenAPI define the wire contract. The React boundary still runtime-validates every response before rendering it.
- Python may use snake_case internally, but the public JSON contract uses camelCase aliases and rejects unexpected fields.
- Every user-owned lookup requires an explicit tenant context. Resource identifiers are never authorization.
- Validate every external, persisted JSON, and model payload at its boundary.
- Never log credentials, prompts, source text, chunks, or document-derived content.
- Render only validated, publication-approved answer views. Raw model output never reaches the interface.
- Evidence Funnel transitions may preserve, narrow, downgrade, or suppress; they may not invent support, repair locators, or upgrade incomplete coverage.
- Workers resume from typed bounded state. They do not own prompt transcripts or replay operational logs into a model.
- Retries are bounded and limited to classified transient failures. Durable operations are idempotent.
- Empty, loading, partial, error, retry, revoked-access, and keyboard behavior are part of the feature definition.
- A new dependency needs one stated purpose and must not duplicate an existing capability.
