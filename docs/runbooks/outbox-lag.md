# Outbox lag

**Fires:** Prometheus alert `OutboxLag`: the oldest unpublished row in the order outbox has been over 60 s old for a minute.
**Arrives:** email through Alertmanager, then a resolved email.

## What it means

`POST /orders` writes the order and its event in one transaction and answers 202. A separate process, the order relay,
publishes the event to EventBridge. When it stops, orders are still accepted and nothing is lost (the rows wait in
PostgreSQL), but they stay PENDING because the event that starts the order never leaves.

## Check

1. **Is the relay running and ready?** Run the `cluster-capacity` workflow and read "Pods that are not Ready, or have
   restarted" for `order-relay`. Not there at all: see [unhealthy-pods](unhealthy-pods.md).
2. **Is it trying and failing?** In Grafana, "Event publish failures (5 min)" above zero means it reaches the bus and is
   refused or errors. "Outbox: unpublished rows" growing while failures stay flat means it is not trying (down, or
   cannot read the database: the gauges then show no value).
3. **What does it say?** Logs Insights on `/aws/containerinsights/loria-retail-dev/application`, adding
   `| filter kubernetes.pod_name like /order-relay/` to the saved query's `fields` line: the failure is in the log lines (a missing
   bus, access denied, a throttle).

## Likely causes

| You see | Cause | Do |
| --- | --- | --- |
| Failures, errors name the bus, started right after a deploy | `EVENT_BUS_NAME` or the chart changed | `app-rollback` for `order-relay`, then fix and redeploy |
| Failures, access denied | The relay's Pod Identity role lost `events:PutEvents` | `platform-create` with `plan`: drift shows up. Apply to restore |
| No failures, no pod | Relay crashed or was never scheduled | [unhealthy-pods](unhealthy-pods.md) |
| Relay not ready, database errors | PostgreSQL unreachable | [database-connectivity](database-connectivity.md) |
| EventBridge itself is degraded | AWS side | Wait; the relay backs off 0.5 to 10 s and drains on its own |

A row that can never be published is retried forever and takes a slot in every batch; a handful is harmless, more than
about 50 would starve healthy rows. Do not delete outbox rows by hand.

## Recovered when

"Outbox lag: oldest unpublished row" is back near zero, the alert resolves, and orders that were PENDING are
CONFIRMED. Every order is published once; consumers ignore a repeat.
