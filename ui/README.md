# CloudPunks marketplace (UI)

A React 19 + TypeScript single-page app, laid out like a marketplace collection page: browse the
100 CloudPunks by colour (red unsold, purple up for bid, blue owned), filter and sort them, buy an
unsold one, put one you own up for bid, make offers, accept one, and follow each order from
`PENDING` to `CONFIRMED` or `REJECTED`. It is a pure client of the public `/api/v1` API
(same-origin through the gateway) and adds no backend behavior. Design: `docs/DESIGN.md`
sections 15 and 16.6.

## Run it

```sh
make up seed        # the whole platform, including the UI image
open http://localhost:8080/
```

`http://localhost:8080/` is the gateway: it serves the app and `/api/v1/*`. The UI container also
listens on `:8005`, but that port serves static files only (no API), so use `:8080`.

Hot reload while editing (needs the stack up): `make ui-dev` → `http://localhost:5173/`, with
`/api` proxied to the gateway and the demo page on.

After changing `gateway/nginx.conf`, reload it: `docker compose ... restart gateway` (Compose does
not recreate a container when only a bind-mounted file changes).

## Make targets

| Target                                                   | What it does                                                                                           |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `make ui-install`                                        | `npm ci`                                                                                               |
| `make ui-dev`                                            | Vite dev server on :5173                                                                               |
| `make ui-types`                                          | regenerate `src/api/generated` from `docs/openapi/*.json`                                              |
| `make ui-lint` / `ui-typecheck` / `ui-test` / `ui-build` | ESLint + Prettier, `tsc`, Vitest (≥ 80% on `src/lib`), production build with the 200 kB gzipped budget |
| `make ui-fmt`                                            | Prettier, writing                                                                                      |
| `make ui-art`                                            | copy the CloudPunk SVGs from `nft-collection/` into `src/assets/cloudpunks`                            |
| `make openapi`                                           | rewrite `docs/openapi/<service>.json` from each service's code                                         |
| `make ui-e2e`                                            | Playwright journeys against the running stack (needs `npx --no-install playwright install chromium`)   |

`make lint` and `make test` run all of the checks above (except `ui-e2e`), and fail on a stale
OpenAPI snapshot, stale generated types or a stale copy of the art.

## Rules that matter

- Money is never a JS `number`: parse to integer minor units (`BigInt`), format by string
  (`31.43 ETH`); compare with `compareDecimal`.
- Stock is never cached, nor anything that decides a tile's colour (owner, listings, bids,
  activity): `staleTime: 0`, `gcTime: 0`, never stored.
- Every purchase and bid sends an `Idempotency-Key`, one per action (`buy:<sku>`, `bid:<sku>`) and
  reused while the request is unchanged; every request sends `X-Correlation-ID`; every error panel
  shows the correlation id.
- Every `localStorage` access is in `src/lib/storage.ts` and wrapped in try/catch.
- No inline script or style (tile colours come from `data-state` and CSS), no external requests, no
  `dangerouslySetInnerHTML` (the CSP forbids it).
- `VITE_DEMO_TOOLS=true` enables `/demo`, which switches the customer id. Local builds only.
