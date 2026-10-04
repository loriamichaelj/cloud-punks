# Retail platform

A retail order platform that runs end to end with Docker Compose, and is built to run on AWS EKS. Customers browse products, place an order, and watch it go `PENDING` → `CONFIRMED` or `REJECTED` through asynchronous events.

```text
browser ─► gateway (nginx :8080) ─┬─ /            ─► ui (React SPA)
                                  └─ /api/v1/... ─► product · inventory · order · notification services

order-service ─► PostgreSQL (order_db) + outbox ─► relay ─► EventBridge ─► SQS ─► inventory / order / notification consumers
product-service ─► PostgreSQL (product_db) + Valkey cache        inventory, notification ─► DynamoDB
```

Locally, EventBridge, SQS, DynamoDB and Lambda run in LocalStack, so no AWS account or credential is involved. The same images also run on AWS EKS, built and operated only by GitHub Actions (see "Running on AWS (dev)" below).

## Prerequisites

- Docker with Compose (developed on OrbStack, Apple Silicon)
- [`uv`](https://docs.astral.sh/uv/) and Python 3.13
- Node 24 (`ui/.nvmrc`), only for the `ui-*` targets
- A LocalStack auth token: <https://app.localstack.cloud>

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
| `ui-install`, `ui-dev`, `ui-types`, `ui-lint`, `ui-typecheck`, `ui-test`, `ui-build` | The UI's own steps (`npm ci`, Vite dev server on `:5173`, generated API types, lint, type check, tests, production build); `lint` and `test` already include them |
| `lock`, `sync` | Refresh or install the uv environment |
| `drills`, `drill-<name>` | The failure drills alone (below) |
| `dlq-peek q=<queue>-dlq`, `dlq-redrive q=<queue>-dlq` | Inspect a dead-letter queue, or move its messages back to the source queue |
| `obs-up`, `obs-down` | Prometheus and Grafana (Compose) |
| `rules-test` | Unit-test the Prometheus alert rules with promtool (part of `lint`; skipped when Docker is not running) |
| `k8s-ingress`, `k8s-deploy`, `k8s-monitoring`, `k8s-monitoring-open`, `k8s-e2e`, `k8s-resilience`, `k8s-rollback r=<release>`, `k8s-down` | The same platform on OrbStack Kubernetes (below) |
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

On AWS the same metrics feed an in-cluster Prometheus, Alertmanager and a view-only Grafana (at `/grafana` on the address `app-expose` opens), logs go to CloudWatch through Container Insights, and CloudWatch alarms and Prometheus alerts arrive by email through one SNS topic. Every alarm and alert has a runbook: start at `docs/runbooks/README.md`.

## Layout

```text
libs/common/       shared package: settings, logging, metrics, health, events, consumer loop
services/*/        product, inventory, order, notification (FastAPI; one image per service, several processes)
functions/         low-stock-alert Lambda
ui/                React SPA (npm project outside the uv workspace)
gateway/           nginx routing, mirrors the future ALB rules
local/             Compose file, LocalStack bootstrap, PostgreSQL init, seed data, Prometheus and Grafana config
tests/e2e/         acceptance steps and failure drills
docs/              DESIGN.md, adr/ (history and as-built notes), runbooks/, generated OpenAPI snapshots
deploy/helm/        the retail-service, secret-store and monitoring charts, and the values per release (local and dev)
infra/terraform/    the bootstrap, dev/platform, dev/cluster-addons and dev/alb-alarms stacks and their modules (applied only from workflows)
scripts/            DLQ tools, OpenAPI export, db_init, the k8s_compose shim, viewer_cidr, package_lambda; their tests are in scripts/tests
.github/workflows/  bootstrap-*, platform-*, addons-*, alarms-* and app-* workflows, plus pr, promote, drills and cluster-capacity (see its README)
```

## Documentation

| Read | For |
| --- | --- |
| `docs/DESIGN.md` | The design: decisions, architecture, API and event contracts, data model, test strategy, the cloud phases, working rules |
| `docs/adr/README.md` | Change history, what each phase actually built, deviations from the design, what went wrong, closed questions |
| `docs/runbooks/README.md` | What to do when an alarm or alert fires; one runbook per failure |
| `.github/workflows/README.md` | Every workflow, the run and teardown order, browser access to dev, pull requests, branches and releases |
| `infra/terraform/README.md` | The stacks, the one-time manual setup, the alarms |
| `docs/openapi/`, `ui/README.md` | The generated API contracts; the UI |

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

## Running on AWS (dev)

The dev environment runs in `us-east-1`: two EKS nodes, RDS for PostgreSQL, ElastiCache for Valkey, DynamoDB, EventBridge and SQS, behind an internal ALB. No AWS credential exists on any laptop (ADR-14). Every change is a workflow, started by hand, with an approval on the `bootstrap` or `dev` GitHub Environment. `app-prepare` runs the checks, builds and pushes the images, and verifies that the pods run the images ECR holds; `app-deploy` then runs the 14-test acceptance suite through the load balancer, and it passes.

Bring-up, in order (details and the teardown order are in `.github/workflows/README.md`):

1. `bootstrap-state-bucket`, then `bootstrap-ci-roles`: the Terraform state bucket and the CI roles. Needs the one-time manual setup in `infra/terraform/README.md` (OIDC provider, bootstrap role, Environments, variables).
2. `platform-create` (plan, then apply): network, ECR, EKS (two nodes), data stores, queues, the in-VPC runner, the CloudWatch alarms and the Container Insights add-on. Set the `dev` environment secret `ALARM_EMAIL` first (an address for alarm and budget emails; confirm the subscription email AWS sends). Then store the runner's GitHub token by hand, as that README says.
3. `addons-create`: the load balancer controller, External Secrets, the secret store, and the Role Prometheus needs.
4. `app-database`, `app-prepare`, `app-deploy`, then `app-seed` and `app-deploy` once more (the first deploy creates the schema; the seed needs it).
5. `alarms-create` (plan, then apply), once `app-deploy` has made the load balancer: the two ALB alarms.
6. `app-expose` (optional): a browser view for one address, held in the `DEV_VIEWER_CIDR` environment secret. It also serves the Grafana dashboards at `/grafana`.

Tear down in the reverse order: `alarms-destroy`, `app-destroy`, `addons-destroy`, `platform-destroy`. Dev costs roughly $360 a month while it runs (a list-price estimate, not measured; the budget alert is $350), so destroy it when idle.

Other workflows: `pr.yml` checks every pull request (lint, tests, image and config scans, Terraform checks, one required `ci` gate); `cluster-capacity` shows how full the cluster is and which pods are unhealthy; `app-rollback` and `promote` roll back and promote.

**State.** Phases 2 to 4 are built and applied in dev (release `v0.1.5`). Never run: the failure drills (`drills.yml` is built), so no alarm has fired in dev and the path from a failure to an email is unproven; the three teardown workflows; `app-rollback` and `promote` (stage and prod are not deployed). Not built: HTTPS and a domain. The open questions are in DESIGN.md section 14; what was built, what differs from the design and what went wrong on the way are in `docs/adr/README.md`, "Cloud (dev on AWS) as built".

