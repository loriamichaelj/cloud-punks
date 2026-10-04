# Local environment

Procedures for the Compose stack and the OrbStack Kubernetes cluster. Everything goes through `make`: Compose needs `IMAGE_TAG` and `--env-file .env`, and every `kubectl` and `helm` call names `--context orbstack`.

## Clean start

```sh
make reset      # stops everything and drops every volume
make up         # builds and starts; blocks until healthy
make seed       # the 100 CloudPunks, one unit of stock each
```

`make seed` is safe to repeat: it never resets a CloudPunk that has been sold.

## After LocalStack restarts

LocalStack keeps its state in memory, so a restart empties DynamoDB: every CloudPunk's stock and owner is gone, while PostgreSQL keeps the old orders, listings and bids. Run `make seed` and the collection comes back all red (unsold). For a fully empty market use the clean start above.

## Failure drills

Each drill breaks one thing, checks that it is detected and that the platform recovers, and puts everything back even when it fails. `make drills` runs all six (`make e2e` runs them too); `make drill-<name>` runs one.

| Target | Breaks | Shows |
| --- | --- | --- |
| `drill-consumer-down` | Stops the inventory consumer, places 5 orders | Orders stay `PENDING`, the queue holds 5, `orders_stuck` rises, then all confirm once and stock drops by exactly 5 |
| `drill-poison` | Publishes a malformed `OrderCreated` | Counted as `poison`, lands in the DLQ after its receives, visible with `dlq-peek`; the redrive tool is exercised on private queues |
| `drill-duplicate` | Sends one real `OrderCreated` twice more | `duplicate` counters rise on both consumers; stock, order and notifications are unchanged |
| `drill-bus-down` | Starts a relay whose EventBridge address is dead | `POST /orders` still answers 202; rows stay unpublished with `last_error`; the real relay drains them with nothing lost or duplicated |
| `drill-cache-down` | Stops Valkey | Reads and orders still work; `cache_errors_total` rises; caching resumes by itself |
| `drill-db-down` | Stops PostgreSQL | Order and product are not ready but alive; requests get `503 STORE_UNAVAILABLE` with `Retry-After`, never 500; recovery needs no restart |

A dead-letter queue: `make dlq-peek q=<queue>-dlq` shows its messages, `make dlq-redrive q=<queue>-dlq` moves them back to the source queue. Fix the cause first, or they return.

## Local Kubernetes (OrbStack)

The processes run in OrbStack's Kubernetes cluster (namespace `retail`) while PostgreSQL, Valkey and LocalStack stay in Compose, which is the shape EKS has. One Helm chart, `deploy/helm/retail-service`, is installed once per process with the values in `deploy/helm/values/`.

```sh
orbctl config set k8s.enable true && orbctl stop && orbctl start   # once; empties LocalStack
make up && make seed     # the stores, and the collection again
make k8s-ingress         # once: Traefik and metrics-server
make k8s-deploy          # build, create Secrets from .env, stop the Compose copies, helm install --rollback-on-failure
make k8s-e2e             # acceptance and market steps, and the browser journeys, through the ingress
make k8s-resilience      # delete each workload's pod under load; no order is lost
```

Open <http://retail.k8s.orb.local/>. `make k8s-monitoring` installs Prometheus, Alertmanager and Grafana, and `make k8s-monitoring-open` port-forwards Grafana to <http://localhost:13000/grafana/>. `make k8s-rollback r=<release> [rev=<n>]` rolls one release back.

- **Compose and the cluster are alternatives.** `k8s-deploy` stops the Compose copies of the processes: two consumers of one queue, or two relays of one outbox, would be wrong. `make k8s-down` removes the releases and `make up` brings the Compose processes back. After changing code and going back to Compose, run `make k8s-down` first, or old cluster releases keep consuming the same queues and the outbox with old images.
- **Enabling Kubernetes empties LocalStack**, so run `make seed` afterwards.

How it was built and what differs from Compose: `docs/adr/README.md`, "Local Kubernetes as built".

## Market activity emails

Locally LocalStack runs SES and keeps each email instead of sending it. List them with `curl localhost:4566/_aws/ses`. In dev they go to the address in the `dev` environment secret `ALARM_EMAIL` (turning that on is in `.github/workflows/README.md`).
