# Database connectivity

**Fires:** CloudWatch `db-cpu`, `db-connections`, `db-freeable-memory`, `db-free-storage`, `db-transaction-ids`. Also what you
reach from [unhealthy-pods](unhealthy-pods.md) or [failed-deployment](failed-deployment.md) when a service answers 503.

## What the platform does when PostgreSQL is unreachable

The product and order APIs answer **503** with `Retry-After` and the code `STORE_UNAVAILABLE`, never a 500, and their
readiness fails so the load balancer stops sending traffic. Liveness stays up, so nothing restarts. The relay and the order
consumer keep retrying. No order is accepted while the database is down. When it returns, the pods become ready again
without a restart.

## By alarm

| Alarm | Means | Do |
| --- | --- | --- |
| `db-free-storage` | Under a tenth of the allocated 20 GiB is free | RDS console: raise allocated storage; find what grew |
| `db-freeable-memory` | Under 128 MiB of memory | Usually too many connections or a heavy query; see below |
| `db-connections` | Over 150 connections | Each API replica holds up to 10 (a pool of 5 plus 5 overflow). A runaway pool or an HPA scale-out. Check replica counts in Grafana |
| `db-cpu` | Over 80% for 15 minutes | A query or a load spike; RDS Performance (console) |
| `db-transaction-ids` | Over a billion transaction IDs used | Wraparound risk: vacuum is not keeping up. RDS console, check the instance's autovacuum; do not ignore |

## It is unreachable

1. **RDS console:** status of `loria-retail-dev`. Not "Available" (rebooting, storage full, failed over): wait or fix there.
2. **Did something change?** `platform-create` with `plan` shows drift in the data module, including the security group rule that lets
   the cluster reach port 5432. Apply restores it.
3. **Passwords.** The apps read `product-app-db`, `product-owner-db`, `order-app-db` and `order-owner-db` from Secrets
   Manager through External Secrets. If authentication fails after a rebuild, run `app-database` (safe to run again; it recreates
   the roles and passwords), then the pods pick the secrets up on their next start.
4. **TLS.** RDS requires TLS (`rds.force_ssl`) and the apps connect with `DB_SSLMODE=require`; an error that names SSL after a change
   to the parameter group or the values is this.

## Recovered when

The relevant alarm returns to OK, the APIs' `/health/ready` is 200 (the pods show Ready in `cluster-capacity`), and an
order placed in the storefront is CONFIRMED.

Do not run `platform-destroy` to fix this: dev's RDS has no final snapshot, so it deletes the data.
