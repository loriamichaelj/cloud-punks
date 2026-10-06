# Workflows

Every workflow is independent: none calls another, each has its own concurrency group, and each assumes only the role its environment allows. Every workflow gets AWS access only through OIDC role assumption; role ARNs and `AWS_REGION` are GitHub Environment variables.

| Workflow | Trigger | Environment | Role (variable) | Concurrency group |
| --- | --- | --- | --- | --- |
| `bootstrap-state-bucket.yml` | `workflow_dispatch` | `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) | `bootstrap-state-bucket` |
| `bootstrap-ci-roles.yml` | `workflow_dispatch` | `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) | `bootstrap-ci-roles` |
| `platform-create.yml` | `workflow_dispatch` with an `action` choice: `plan` (print the plan) or `apply` (plan, then apply after a second approval; the plan reads the `dev` environment secret `ALARM_EMAIL` for the alarm and budget email) | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `platform-destroy.yml` | `workflow_dispatch` (a saved `plan -destroy`, then a second approval to apply it) | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `addons-create.yml` | `workflow_dispatch` with an `action` choice: `plan` or `apply` (plan, then apply after a second approval). Runs on the `retail-vpc` runner | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `addons-destroy.yml` | `workflow_dispatch` (a saved `plan -destroy`, then a second approval). Runs on the `retail-vpc` runner | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `alarms-create.yml` | `workflow_dispatch` with an `action` choice: `plan` or `apply` (plan, then apply after a second approval). Hosted runner. Creates the two ALB alarms (5xx rate, p95 latency); needs the ALB, so run it after `app-deploy` | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `alarms-destroy.yml` | `workflow_dispatch` (a saved `plan -destroy`, then a second approval). Hosted runner. Works after the ALB is gone | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `dns-create.yml` | `workflow_dispatch` with an `action` choice: `plan` or `apply` (plan, then apply after a second approval). Hosted runner. The `dev/dns` stack: the ACM certificate for `dev.<domain>` and `internal.dev.<domain>` with its DNS validation, and the private zone. Reads the `dev` environment variable `DEV_DOMAIN` and stops if it is empty. Run after `platform-create` and before `app-deploy` | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `dns-destroy.yml` | `workflow_dispatch` (a saved `plan -destroy`, then a second approval). Hosted runner. Never touches the domain or its zone | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `alb-dns-create.yml` | `workflow_dispatch` with an `action` choice: `plan` or `apply`. Hosted runner. The `dev/alb-dns` stack: alias records from the two names to the two ALBs. Looks up each ALB's address, so run it after `app-deploy` (and `app-expose`), and again whenever an ALB is recreated | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `alb-dns-destroy.yml` | `workflow_dispatch` (a saved `plan -destroy`, then a second approval). Hosted runner. Needs no ALB | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `cluster-capacity.yml` | `workflow_dispatch`. Read-only: pods per namespace against the node's pod limit, CPU and memory requested against allocatable, the pods that are not Ready or have restarted with the recent warning events, and what the nodes and the heaviest pods use now. Runs on the `retail-vpc` runner (approval) | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`; the deploy role cannot see nodes) | `app-dev` |
| `drills.yml` | `workflow_dispatch` with a `drill` choice (`consumer-down`, `bus-down`; more to come). Breaks one thing by changing configuration, waits for the platform to notice (Prometheus alerts, and the alarm and alert emails), restores it and checks the recovery. Takes 5 to 15 minutes. A final step puts everything back if the run was killed. **Built but never run** (the drills were skipped). Runs on the `retail-vpc` runner (approval) | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |
| `app-prepare.yml` | `workflow_dispatch`. Everything before a deploy, in one run. Jobs: `prepare` (names the tag `sha-<git sha>`; only `dev` publishes), `test` (the checks `pr.yml` runs, all of them, as parallel legs on hosted runners with no AWS: `code`, `terraform`, `config-scan`, `workflows` and one `image` leg per image, arm64 build then Trivy; any branch), `build` (pushes the five images to ECR and lists their digests in the run summary; an existing tag is not rebuilt; dev only, approval), `verify` (read-only: ECR against the cluster, and prints the tag to paste into `app-deploy`; dev only, runner, approval), `notify`. From another branch only `prepare`, `test` and `notify` run | `dev` (`build` and `verify`) | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |
| `app-database.yml` | `workflow_dispatch`. Creates `product_db` and `order_db`, their owner and app roles, and the four passwords in Secrets Manager. Runs on the `retail-vpc` runner (approval) | `dev` | `cloudbatch818-loria-retail-db-dev` (`AWS_ROLE_ARN_DB`) | `app-dev` |
| `app-deploy.yml` | `workflow_dispatch` with an optional image `tag` (default `sha-<this commit>`). Jobs: `deploy` (checks the images exist, Helm on the runners, e2e; approval), `notify` | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |
| `app-seed.yml` | `workflow_dispatch`. Loads the 100 CloudPunks into `product_db` and one unit of stock each into the inventory table, with the same `local/seed/seed.py` as `make seed`. Runs on the `retail-vpc` runner (approval). Safe to run again | `dev` | `cloudbatch818-loria-retail-db-dev` (`AWS_ROLE_ARN_DB`) | `app-dev` |
| `app-reset.yml` | `workflow_dispatch` with a `confirm` input that must be exactly `reset` (checked on a hosted runner before anything else). Puts the market back to a clean state: deletes every order, listing and bid in `order_db` (so the activity feed is empty) and returns all 100 CloudPunks to the platform, with `local/seed/reset.py`. The catalog and the releases are untouched. Runs on the `retail-vpc` runner (approval) | `dev` | `cloudbatch818-loria-retail-db-dev` (`AWS_ROLE_ARN_DB`) | `app-dev` |
| `app-expose.yml` | `workflow_dispatch` with an `action` choice: `expose` or `remove`. Installs a second, internet-facing ALB for the storefront and, at `/grafana`, the read-only Grafana dashboards, reachable only from the address in the `dev` environment secret `DEV_VIEWER_CIDR`. Runs on the `retail-vpc` runner (approval) | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |
| `app-rollback.yml` | `workflow_dispatch` with a `release` choice (`all` or one release) and an optional `revision` (one release only). `helm rollback --wait`, then the storefront must answer. Runs on the `retail-vpc` runner (approval) | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |
| `promote.yml` | `workflow_dispatch` with a required `tag`, run from the `stage` or `prod` branch, which picks the Environment. Deploys that tag's image digests. **Not run: stage and prod are not deployed** | `stage` or `prod` | its own `AWS_ROLE_ARN_DEPLOY` (not set) | `promote-<branch>` |
| `pr.yml` | `pull_request` into `dev`, `stage`, `prod`. Hosted runners, read-only token, no secrets, no AWS. Jobs: `detect`, `code`, `images` (five, with Trivy), `terraform`, `config-scan`, `workflows`, and `ci`, the one required check | none | none | `pr-<number>` |
| `app-destroy.yml` | `workflow_dispatch` with a required `tag` (an image tag, or `all`) and an optional `uninstall_releases` (off by default; needs the runners) | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |

## Run order

1. `bootstrap-state-bucket.yml`: creates `loria-retail-tfstate-<account-id>-<region>`. Safe to run again.
2. `bootstrap-ci-roles.yml`: creates the CI roles. Fails early if the bucket is missing.
3. `platform-create.yml`: the network, ECR repositories, EKS cluster, data stores, queues and the runner. Run `plan` first. Then store the runner's GitHub token (see `infra/terraform/README.md`).
4. `addons-create.yml`: on the runner, the `retail` namespace, the AWS Load Balancer Controller and External Secrets Operator.
5. `app-database.yml`: on the runner, the application databases, roles and their four Secrets Manager passwords. Needs `platform-create` and the db role from `bootstrap-ci-roles`. Safe to run again.
6. `app-prepare.yml` (`prepare`, `test`, `build`, `verify`, `notify`): the checks, then the images pushed to ECR (needs the repositories from `platform-create`), then a comparison of ECR with the cluster. Its run summary starts with the tag to paste into `app-deploy`. Two approvals: `build`, then `verify`.
7. `app-deploy.yml`: deploys a pushed tag to the cluster and runs the acceptance suite. On a fresh environment its e2e step is red the first time, because the catalog is empty (see 8).
8. `app-seed.yml`: after the first `app-deploy` (its `product-service` release migrates the schema), loads the catalog and stock. Then run `app-deploy` again, or just use the app.
9. `app-expose.yml` (optional): opens the storefront to one browser address, see below.
10. `alarms-create.yml`: after the first `app-deploy` (the ALB must exist), the two ALB alarms. Safe to run again; it re-reads the ALB's identifier, which changes if the ALB is recreated.
11. HTTPS and a domain (optional, needs a registered domain and `DEV_DOMAIN`; the whole sequence is `docs/runbooks/https-and-domain.md`): `dns-create.yml` goes between 3 and 7, so the certificate is issued before `app-deploy` asks for it; `alb-dns-create.yml` goes after `app-deploy` and `app-expose`, and `app-deploy` once more shows the HTTPS check passing. Without `DEV_DOMAIN` every workflow serves plain HTTP, as before.

Once the app is up, `app-reset.yml` empties the market (orders, listings, bids, activity) and makes every CloudPunk red again; `app-seed` cannot, by design. Run it while nobody is buying.

Tearing down, in this order (the whole procedure, with what survives and the rebuild, is `docs/runbooks/rebuild.md`):

1. `app-destroy.yml` with `tag` = `all` and `uninstall_releases` on: removes every Helm release in `retail`, including `gateway-public`, so the load balancer controller deletes both ALBs while it still runs, then every image in the five ECR repositories. Both inputs matter: the certificate is attached to the ALB listeners and cannot be deleted before they are gone, and the repositories are not force-deleted, so `platform-destroy` stops on one that still holds images. Needs the deploy role's `ecr:BatchDeleteImage`, which `bootstrap-ci-roles` grants.
2. `alb-dns-destroy.yml`, `dns-destroy.yml`, then `alarms-destroy.yml` (the ones that were created): the alias records, then the certificate and the private zone (the records live in that zone, so they go first), then the ALB alarms. They go before `platform-destroy`, which refuses while any of them has resources. The domain and its public zone are never touched.
3. `addons-destroy.yml`: removes the add-ons while the cluster still runs.
4. `platform-destroy.yml`: removes the platform stack. It refuses to start while the addons, alarms or DNS stacks still have resources; it reads Terraform state only, so it cannot see an ALB or an image. The bucket and the CI roles stay.

`platform-create`, `platform-destroy`, `addons-create`, `addons-destroy`, `alarms-create`, `alarms-destroy`, `dns-create`, `dns-destroy`, `alb-dns-create` and `alb-dns-destroy` share the group `platform-dev`, so none of them overlap. `app-prepare`, `app-database`, `app-seed`, `app-reset`, `app-deploy`, `app-expose` and `app-destroy` share `app-dev`.

`app-deploy.yml` installs every release and the internal ALB, then runs the acceptance suite in cloud mode (`E2E_K8S=1 E2E_CLOUD=1`): orders go through the ALB, the four APIs are port-forwarded to the runner's localhost, and `scripts/k8s_compose.py` stands in for Compose with kubectl. One check is skipped there, the dead-letter-queue count inside step 9, because the deploy role may not read the queues; the low-stock Lambda test reads the real CloudWatch log group. Run `app-seed.yml` once first, or the catalog is empty and step 1 fails. The suite includes three market tests (buy from the platform, put up for bid, bid, accept and resell; take a CloudPunk off the market; four buyers race for one) on the suite's own `E2E-N` item. Four more tests run only in the cloud (17 in all there): one traces an order across the services in CloudWatch with Logs Insights (needs Container Insights, see `infra/terraform/README.md`); one checks that Prometheus scrapes all eight processes, one that the alert rules are loaded and Alertmanager is ready, and one that Grafana is up with the dashboard and is view only (all need the `monitoring` release, which `app-deploy` installs last, after `addons-create` has created Prometheus's Role and `platform-create` Alertmanager's). The drills and the UI journeys are not run in the cloud. `app-prepare.yml` publishes only after its own checks passed, and its `verify` job is the way to see whether what runs is what ECR holds. Only dev is deployed. `stage` and `prod` exist as branches and GitHub Environments, with no roles, variables or cluster behind them.

## Seeing the app in a browser

The internal ALB is reachable only from inside the VPC, and no laptop has AWS access (ADR-14). `app-expose.yml` adds a second ALB for one person:

1. Find your public address (for example, https://checkip.amazonaws.com).
2. Store it as the `dev` **environment secret** `DEV_VIEWER_CIDR`, as `x.x.x.x/32` or a bare address: GitHub, Settings, Environments, `dev`, Add environment secret. Do not use a variable (variables print in logs) and never commit it. Only jobs that pass the `dev` approval can read it, and logs mask it.
3. Run **App: expose** with `expose`, approve it, and open the address in its run summary. The ALB takes a few minutes to answer the first time.
4. When your address changes, update the secret and run `expose` again. Run `remove` when you are done; **App: destroy** with `uninstall_releases` also removes it.

Once it is installed, every `app-deploy` also refreshes its routes from `values-ingress-public-dev.yaml` (with `--reuse-values`, so the stored address is kept and that job never reads the secret); `app-deploy` never installs it. Without that, a new API path added to both Ingress files reaches the internal ALB only, and on the viewer ALB it falls through to the UI and answers HTML.

With `DEV_DOMAIN` set and the DNS stacks applied, the address in the run summary is `https://dev.<domain>` instead: port 80 redirects to 443 with an ACM certificate, and the allow-list above is unchanged (HTTPS protects the traffic; only the address list keeps strangers out). Run **ALB DNS: create** after the first `expose` and again after any `remove` then `expose`, because the ALB's own name changes.

`scripts/viewer_cidr.py` refuses anything wider than a `/24`, any private address, and `0.0.0.0/0`. Without a domain the ALB is plain HTTP, there is no login, and the API's admin endpoints are unauthenticated, which is why it is limited to one address and meant for dev only. The "demo tools" page of the UI is not in the cloud build (`VITE_DEMO_TOOLS` is off outside local), so stock and prices cannot be set from the browser.

**Not yet exercised:** the `remove` action of `app-expose` has never been run (`app-destroy` with `uninstall_releases` removes the viewer ALB too). The six destroy workflows have each run once in dev, in the order above.

## Market activity emails

Every sale, bid and listing on a CloudPunk emails the address in the `dev` environment secret `ALARM_EMAIL`, with the CloudPunk's picture (DESIGN.md section 16.11). It is part of the platform stack, so to turn it on (or after changing the function):

1. `bootstrap-ci-roles`: the platform apply role gains `ses:*`. Once.
2. `platform-create` (plan, then apply): the SES identity for the address, the `market-activity-email` function (its zip comes from `scripts/package_lambda.py`, which the workflow already runs), its rule, role and DLQ.
3. Click the link in the "Amazon Web Services – Email Address Verification Request" email AWS sends to that address. Nothing is delivered until then. Once.
4. `app-prepare`, then `app-deploy`: order-service starts writing the `MarketActivity` events.

The sender is the same address (the SES identity is the address, not the dev domain), so mark the first email "not spam" if it lands there. Without `ALARM_EMAIL` none of it is created.

## Pull requests, branches and releases

`pr.yml` needs no secrets and no setup. It runs `make lint test`, builds and Trivy-scans the five images, checks Terraform (fmt, validate, tflint, Checkov) and the workflows (actionlint), and ends in `ci`. A change that touches only docs runs almost nothing; a change to `pr.yml` runs everything. Integration tests, drills and browser journeys are not in CI (they need LocalStack); `app-deploy.yml` runs the acceptance suite against AWS instead.

| Branch | Direct push | Pull request | Required |
| --- | --- | --- | --- |
| `dev` | yes (owner) | not required | no force push, no deletion |
| `stage`, `prod` | never, admins included | yes | 1 approving review (stale approvals dismissed, the last pusher cannot approve), `ci` passing and up to date, no force push, no deletion |

Promotion is a pull request `dev` to `stage` (then `stage` to `prod`), a reviewer's merge, then `promote.yml` run from that branch and approved in its Environment. A solo owner cannot approve their own pull request, so the first promotion needs a second reviewer. This path has never run.

Rolling back: run **App: rollback** with `all`, or with one release and a `revision`. Check afterwards with the `verify` job of **App: prepare** (it also runs the checks and finds the images already built). It changes what runs, not the database.

Releases are tags on `dev` with a GitHub Release. `v0.1.0` was the first and `v1.0.0` is the current one. `v1.0.0` keeps its version and its tag is moved to a later `dev` commit when the release is updated (the owner's choice, 4 Oct 2026): the commit it points at is the one in the release notes.
