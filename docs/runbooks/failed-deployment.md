# Failed deployment and rollback

**Fires:** an `app-deploy` run that is red, or after a deploy the CloudWatch alarms `alb-5xx-rate` (over 1% of requests are
5xx for two periods) or `alb-p95-latency` (p95 over 0.5 s for three periods).

## Read the run first

Open the red `app-deploy` run. The step that failed says which of these it is:

| Failing step | Cause | Do |
| --- | --- | --- |
| Check the images exist | The tag is not in ECR | Run `app-prepare`, use the tag its `verify` prints |
| Check the dev values exist | A values file is missing | Add it and redeploy |
| Deploy the releases, the `secrets` release | External Secrets did not create a database secret | Secrets Manager must hold `loria-retail-dev/<name>` with a `password` key. Run `app-database`, then redeploy |
| Deploy the releases, a process release | The pods did not become Ready, or the migration job failed | "Show cluster state on failure" in the run, then [unhealthy-pods](unhealthy-pods.md) |
| Find the ALB | The Ingress has no address after 10 minutes | The load balancer controller: `addons-create` with `plan` |
| E2E acceptance | The suite found a real problem | Read the failed test's output and, for the low-stock path, the "Show the low-stock path on failure" step |

**A failed release rolls itself back** (`--rollback-on-failure`), so after a red run the cluster can be mixed: some releases
new, the failed one at its previous revision. Run `app-prepare` and read `verify` to see what runs.

## Roll back on purpose

1. Run **`app-rollback`** with `release: all` (every release goes back one revision, right when they were last deployed
   together), or one release and a `revision` to go further back. It waits for the pods and checks the storefront answers.
2. Run `app-prepare` (its `verify` job) to confirm what is running is what ECR holds.

A rollback changes what runs, **not the database**. Migrations are forward-only and backward compatible, so the earlier release
runs on the newer schema. If a change was not backward compatible, do not roll back: fix forward and redeploy.

## The ALB alarms

`alb-5xx-rate` or `alb-p95-latency` soon after a deploy: roll back as above. Otherwise they point at a dependency, so see
[unhealthy-pods](unhealthy-pods.md) first (pods missing from rotation return 503 from the ALB itself), then
[database-connectivity](database-connectivity.md).

## Recovered when

`app-deploy` (or `app-rollback`) is green, the storefront answers, and the alarms return to OK.
