# Extent web

The Extent frontend uses Next.js, React, and TypeScript. It consumes the generated OpenAPI contract in `src/generated`, proxies browser API requests through the same-origin `/api/backend/*` boundary, and reads the prepared public sample from the API.

## Run locally

```bash
pnpm install
pnpm dev:web
```

The app opens at `http://localhost:3000`. In development it proxies `/api/backend/*` to `http://127.0.0.1:8000`. Set `EXTENT_API_PROXY_TARGET` to use another backend origin.

## Routes

- `/` — product introduction
- `/connect` — Google Drive connection and folder preparation
- `/sample` — prepared fictional evidence workspace
- `/workspace/[id]` — live workspace backed by the existing API

## Verify

```bash
pnpm lint:web
pnpm typecheck:web
pnpm build:check
```
