# Runbooks

Five runbooks, each tied to the alarms and alerts that point at it (DESIGN.md section 13), and one for the
local environment. Every alarm and alert in dev is in the table below. If one is not,
`scripts/tests/test_runbooks.py` fails.

**Status: written from the design and from reading the code, not from following them during a drill.** The
failure drills on EKS were skipped, so no alarm or alert has ever fired in dev and no step below has been
exercised against a real failure. Treat a step that does not match what you see as a runbook bug and fix the
runbook.

## Where the alarms come from

Everything arrives by email through one SNS topic (`loria-retail-dev-alarms`):

- **CloudWatch alarms** named `loria-retail-dev-<name>` (the table's first column). They send ALARM and, when
  fixed, OK.
- **Prometheus alerts** (`OutboxLag`, `OrdersStuck`, `PodRestartingRepeatedly`, `TargetDown`) through
  Alertmanager, firing and resolved. Each names its runbook in the alert.

| Alarm or alert | Means | Runbook |
| --- | --- | --- |
| `OutboxLag` | Orders are accepted but the relay is not publishing them | [outbox-lag](outbox-lag.md) |
| `OrdersStuck` | Orders have been PENDING for over five minutes | [stuck-queue](stuck-queue.md) |
| `queue-age-to-inventory`, `queue-age-to-order`, `queue-age-to-notification` | A queue's oldest message is over 120 s old: its consumer is not consuming | [stuck-queue](stuck-queue.md) |
| `dlq-to-inventory`, `dlq-to-order`, `dlq-to-notification`, `dlq-low-stock` | A message is in a dead-letter queue | [stuck-queue](stuck-queue.md) |
| `rule-failed-to-inventory`, `rule-failed-to-order`, `rule-failed-to-notification`, `rule-failed-low-stock` | EventBridge could not deliver to a target | [stuck-queue](stuck-queue.md) |
| `lambda-low-stock-errors` | The low-stock Lambda raised an error | [stuck-queue](stuck-queue.md) |
| `PodRestartingRepeatedly` | A process restarted more than 3 times in 10 minutes | [unhealthy-pods](unhealthy-pods.md) |
| `TargetDown` | Prometheus cannot scrape a process for 2 minutes | [unhealthy-pods](unhealthy-pods.md) |
| `db-cpu`, `db-connections`, `db-freeable-memory`, `db-free-storage`, `db-transaction-ids` | RDS is under pressure or filling | [database-connectivity](database-connectivity.md) |
| `alb-5xx-rate`, `alb-p95-latency` | The load balancer is returning 5xx or answering slowly | [failed-deployment](failed-deployment.md), then [unhealthy-pods](unhealthy-pods.md) and [database-connectivity](database-connectivity.md) |
| An `app-deploy` run that is red | A release or the acceptance suite failed | [failed-deployment](failed-deployment.md) |

## Procedures

Not tied to an alarm:

- [local-environment](local-environment.md): the clean start, restarting LocalStack, the failure drills and the local Kubernetes cluster.
- [https-and-domain](https-and-domain.md): registering the dev domain, the order of the DNS workflows, and what to check when HTTPS does not answer.
- Dev environment (bring-up, teardown, resetting the market, opening it in a browser): `.github/workflows/README.md`.

## What a person can use

No laptop has AWS or cluster access (ADR-14), so these runbooks use only:

- **Workflows** (GitHub, Actions): `cluster-capacity` (which pods are not Ready, restarts, warning events, how
  full the nodes are), `app-prepare` (its `verify` job: what runs against what ECR holds), `app-deploy`,
  `app-rollback`, `app-database`, `platform-create` with `plan` (shows drift, changes nothing).
- **Grafana**, at `/grafana` on the viewer address (run `app-expose` with `expose` first). The "Retail platform"
  dashboard has the four service level indicators and panels for requests, events, queues, the outbox and stuck
  orders.
- **CloudWatch** in the console: alarms, Container Insights, and Logs Insights with the saved query
  `retail/trace-a-correlation-id` on the application log group.
- **SQS and RDS in the console**, with your own sign-in, for dead-letter queues and database metrics.

## Known gaps

There is no workflow to restart a Deployment, to read a database, or to peek and redrive a dead-letter queue in
the cloud (the `make dlq-*` tools are for the local stack). The runbooks use the console for the queues and
`app-rollback` where a restart would help, and say so where it matters.
