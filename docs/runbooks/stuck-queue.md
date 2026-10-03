# Stuck queue, dead letters and undelivered events

**Fires:** Prometheus `OrdersStuck`; CloudWatch `queue-age-to-*`, `dlq-*`, `rule-failed-*`, `lambda-low-stock-errors`.

## What each one means

| Trigger | Meaning |
| --- | --- |
| `OrdersStuck` | Orders have been PENDING for over five minutes (counted by the relay every 60 s) |
| `queue-age-to-inventory` / `-to-order` / `-to-notification` | The oldest message in that queue is over 120 s old: nothing is consuming it |
| `dlq-*` | A message failed five receives and was parked in a dead-letter queue. Kept 14 days |
| `rule-failed-*` | EventBridge could not deliver an event to a queue or the Lambda |
| `lambda-low-stock-errors` | The low-stock Lambda raised an error |

The queues are `loria-inventory-order-events`, `loria-order-inventory-events`, `loria-notification-events`, each with a
`-dlq`, and `loria-low-stock-alert-dlq` for the Lambda.

## A queue is not being consumed (`queue-age-*`, `OrdersStuck`)

1. `cluster-capacity`: is the consumer pod there and Ready? Consumers: `inventory-consumer` (reads the inventory
   queue), `order-consumer`, `notification-consumer`. If not, see [unhealthy-pods](unhealthy-pods.md).
2. Pod is Ready but messages age: in Grafana, "Poison and error outcomes (last 5 min)" shows `error` rising: the handler
   is failing (usually a store it needs is unreachable: DynamoDB, or PostgreSQL for the order consumer). Logs Insights
   on the application log group, filtering `kubernetes.pod_name like /inventory-consumer/` (or the consumer you are looking at).
3. Orders PENDING but queue empty: the event never left the outbox, so see [outbox-lag](outbox-lag.md).
4. After a fix the queue drains by itself. No redrive is needed for messages still in the queue.

## A message is in a dead-letter queue (`dlq-*`)

It failed five times, about five minutes, so it is poison (cannot be parsed or is invalid) or its handler kept failing.

1. **Read it.** SQS console, the `-dlq` queue, "Send and receive messages", "Poll for messages". The logs name the
   reason by field path, never the payload values.
2. **Decide.**
   - The consumer has since been fixed, or the failure was transient: **redrive**. SQS console, the DLQ, "Start DLQ
     redrive", back to the source queue. Do it only after the cause is fixed, or it returns here in five minutes.
   - It can never succeed (malformed from a bad producer): **delete it** (purge the DLQ if it holds only that).
3. Act within 14 days or the message expires.

Find the order behind a message with the saved Logs Insights query `retail/trace-a-correlation-id`, pasting the
correlation id from the log line.

## EventBridge cannot deliver (`rule-failed-*`)

The rule's target is a queue or the Lambda. Usual causes are the queue policy no longer trusting the rule, or the
Lambda permission missing. Run `platform-create` with `plan`: drift in the events module shows here. Apply restores it.
Events that failed delivery are not retried forever; the 7-day archive on the bus can replay them (EventBridge console).

## The Lambda (`lambda-low-stock-errors`)

It logs to `/aws/lambda/loria-low-stock-alert`; a failed asynchronous invoke retries twice, then goes to
`loria-low-stock-alert-dlq`. It sends no customer-facing message, so there is no urgency beyond the alert itself.

## Recovered when

Queue age alarms return to OK, `OrdersStuck` resolves, orders that were PENDING are CONFIRMED or REJECTED, and the
dead-letter queues are empty.
