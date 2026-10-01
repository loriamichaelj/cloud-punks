# Retail demo shop (UI)

A React 19 + TypeScript single-page app: browse the catalog, build a basket, place an order and
watch it move `PENDING → CONFIRMED | REJECTED`. It is a pure client of the public `/api/v1` API
(same-origin through the gateway) and adds no backend behavior. Design: `docs/DESIGN.md` section 15.

## Run it

```sh
make up seed        # the whole platform, including the UI image
open http://localhost:8080/
```

`http://localhost:8080/` is the gateway: it serves the app and `/api/v1/*`. The UI container also
listens on `:8005`, but that port serves static files only (no API), so use `:8080`.

Hot reload while editing (needs the stack up): `make ui-dev` → `http://localhost:5173/`, with
`/api` proxied to the gateway and the demo tools page on.

After changing `gateway/nginx.conf`, reload it: `docker compose ... exec gateway nginx -s reload`
(Compose does not recreate a container when only a bind-mounted file changes).

## Make targets

| Target | What it does |
| --- | --- |
| `make ui-install` | `npm ci` |
| `make ui-dev` | Vite dev server on :5173 |
| `make ui-types` | regenerate `src/api/generated` from `docs/openapi/*.json` |
| `make ui-lint` / `ui-typecheck` / `ui-test` / `ui-build` | ESLint + Prettier, `tsc`, Vitest (≥ 80% on `src/lib`), production build with the 200 kB gzipped budget |
| `make openapi` | rewrite `docs/openapi/<service>.json` from each service's code |
| `make ui-e2e` | Playwright journeys against the running stack |

`make lint` and `make test` run all of the checks above (except `ui-e2e`), and fail on a stale
OpenAPI snapshot or stale generated types.

## Rules that matter

- Money is never a JS `number`: parse to integer minor units (`BigInt`), format by string.
- Stock is never cached (`staleTime: 0`, `gcTime: 0`) and never stored.
- Every order submit sends an `Idempotency-Key`, reused for the same basket; every request sends
  `X-Correlation-ID`; every error panel shows the correlation id.
- Every `localStorage` access is in `src/lib/storage.ts` and wrapped in try/catch.
- No inline script or style, no external requests, no `dangerouslySetInnerHTML` (the CSP forbids it).
- `VITE_DEMO_TOOLS=true` enables `/demo` (unauthenticated admin calls). Local builds only.
