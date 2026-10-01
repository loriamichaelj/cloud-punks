# Retail platform

A retail order platform that runs end to end with Docker Compose, and is built to run on AWS EKS. Customers browse products, place an order, and watch it go `PENDING` → `CONFIRMED` or `REJECTED` through asynchronous events.

```text
browser ─► gateway (nginx :8080) ─┬─ /            ─► ui (React SPA)
                                  └─ /api/v1/... ─► product · inventory · order · notification services

order-service ─► PostgreSQL (order_db) + outbox ─► relay ─► EventBridge ─► SQS ─► inventory / order / notification consumers
product-service ─► PostgreSQL (product_db) + Valkey cache        inventory, notification ─► DynamoDB
```

EventBridge, SQS, DynamoDB and Lambda run in LocalStack, so no AWS account or credential is ever involved.

## Prerequisites

- Docker with Compose (developed on OrbStack, Apple Silicon)
- [`uv`](https://docs.astral.sh/uv/) and Python 3.13
- Node 24 (`ui/.nvmrc`), only for the `ui-*` targets
- A free LocalStack Hobby auth token (non-commercial use): <https://app.localstack.cloud>

## Run it

```sh
make .env                # copies .env.example to .env (git-ignored)
# edit .env: set LOCALSTACK_AUTH_TOKEN and LOCALSTACK_TAG
make up                  # build and start everything; blocks until healthy
make seed                # 5 categories, 20 products, stock levels (idempotent)
```

Then open <http://localhost:8080/>. Run everything through `make`: Compose needs `IMAGE_TAG` and `--env-file .env`, and images are tagged `dev-<git sha>`, never `:latest`.

LocalStack keeps its state in memory, so after any restart of it run `make seed` again.

| What | Where |
| --- | --- |
| UI and API (use this one) | <http://localhost:8080/> and `/api/v1/...` |
| Product, inventory, order, notification services | `:8001`, `:8002`, `:8003`, `:8004` (`/health/ready`, `/metrics`, `/docs`) |
| Prometheus, Grafana (`make obs-up`) | <http://localhost:9090>, <http://localhost:3000> |

## Make targets

| Target | Purpose |
| --- | --- |
| `up`, `down`, `reset` | Start, stop, or stop and drop all data (`reset` then `up` is the clean start) |
| `seed` | Catalog into PostgreSQL and stock into DynamoDB |
| `logs s=<service>` | Follow Compose logs |
| `lint`, `fmt` | ruff, mypy per service, OpenAPI and UI type checks, eslint, prettier, production build |
| `test` | Unit tests (hermetic: no AWS, no LocalStack) and UI tests; 80% coverage gates |
| `itest` | Integration tests against the running stack (pauses the real relay for the run) |
| `e2e` | Acceptance steps 1 to 10 and every failure drill, through the gateway |
| `ui-e2e` | Browser journeys (Playwright, headless Chromium) |
| `drills`, `drill-<name>` | The failure drills alone (below) |
| `dlq-peek q=<queue>-dlq`, `dlq-redrive q=<queue>-dlq` | Inspect a dead-letter queue, or move its messages back to the source queue |
| `obs-up`, `obs-down` | Prometheus and Grafana |
| `k8s-ingress`, `k8s-deploy`, `k8s-e2e`, `k8s-resilience`, `k8s-rollback r=<release>`, `k8s-down` | The same platform on OrbStack Kubernetes (below) |
| `openapi` | Rewrite the OpenAPI snapshots in `docs/openapi/` |

The full check, from nothing:

```sh
make reset && make up && make seed
make lint test itest e2e ui-e2e
```

## Failure drills

Each drill breaks one thing, checks that it is detected, and checks that the platform recovers. They put everything back even when they fail.

| Target | Breaks | Shows |
| --- | --- | --- |
| `drill-consumer-down` | Stops the inventory consumer, places 5 orders | Orders stay `PENDING`, the queue holds 5, `orders_stuck` rises, then all confirm once and stock drops by exactly 5 |
| `drill-poison` | Publishes a malformed `OrderCreated` | Counted as `poison`, lands in the DLQ after its receives, visible with `dlq-peek`; the redrive tool is exercised on private queues |
| `drill-duplicate` | Sends one real `OrderCreated` twice more | `duplicate` counters rise on both consumers; stock, order and notifications are unchanged |
| `drill-bus-down` | Starts a relay whose EventBridge address is dead | `POST /orders` still answers 202; rows stay unpublished with `last_error`; the real relay drains them with nothing lost or duplicated |
| `drill-cache-down` | Stops Valkey | Reads and orders still work; `cache_errors_total` rises; caching resumes by itself |
| `drill-db-down` | Stops PostgreSQL | Order and product are not ready but alive; requests get `503 STORE_UNAVAILABLE` with `Retry-After`, never 500; recovery needs no restart |

## Observability

Every process logs JSON with a `correlation_id` (send `X-Correlation-ID`, or one is generated) and serves Prometheus metrics. `make obs-up` adds Prometheus and one Grafana dashboard, **Retail platform**, with request rate, 5xx ratio and latency per service, events consumed by outcome, queue and dead-letter depth, outbox size and lag, stuck orders, and time from `PENDING` to a final status. It is local-only: Grafana allows anonymous read access and both ports are bound to loopback.

A stuck-order sweeper in the relay process counts orders `PENDING` for more than 5 minutes into the `orders_stuck` gauge (every 60 s) and logs them. It changes nothing; it is the alarm source for the stuck-queue runbook.

## Layout

```text
libs/common/       shared package: settings, logging, metrics, health, events, consumer loop
services/*/        product, inventory, order, notification (FastAPI; one image per service, several processes)
functions/         low-stock-alert Lambda
ui/                React SPA (npm project outside the uv workspace)
gateway/           nginx routing, mirrors the future ALB rules
local/             Compose file, LocalStack bootstrap, PostgreSQL init, seed data, Prometheus and Grafana config
tests/e2e/         acceptance steps and failure drills
docs/              DESIGN.md, ADR notes, generated OpenAPI snapshots
```

## Local Kubernetes (OrbStack)

The processes can run in OrbStack's Kubernetes cluster (namespace `retail`) while PostgreSQL, Valkey and LocalStack stay in Compose, which is the shape EKS will have. One Helm chart, `deploy/helm/retail-service`, is installed once per process with the values in `deploy/helm/values/`. Every `kubectl` and `helm` call in the Makefile names `--context orbstack`.

```sh
orbctl config set k8s.enable true && orbctl stop   # once; the next docker command restarts OrbStack
make k8s-ingress         # once: Traefik and metrics-server
make k8s-deploy          # build, create Secrets from .env, stop the Compose copies, helm install --rollback-on-failure
make seed                # if LocalStack restarted
make k8s-e2e             # acceptance steps and browser journeys through the ingress
make k8s-resilience      # delete each workload's pod under load; no order is lost
```

Open <http://retail.k8s.orb.local/>. `make k8s-down` removes the releases and `make up` brings the Compose processes back. How it works and what differs from Compose: `docs/adr/README.md`.

Next: the cloud, pipeline and Terraform strategy pass (section 13 of the design), then AWS.
