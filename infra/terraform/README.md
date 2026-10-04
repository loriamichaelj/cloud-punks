# Terraform

Applied only from GitHub Actions (ADR-14); nothing here is run from a laptop. Locally: `terraform fmt`, `terraform init -backend=false` and `terraform validate`.

The record of what was built, what differs from DESIGN.md and what went wrong on the way is in `docs/adr/README.md`, "Cloud (dev on AWS) as built".

## One-time manual setup

Done once, by the owner, in the console or CloudShell. Nothing else is created by hand.

1. Create the IAM OIDC provider `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`) and the role `cloudbatch818-loria-retail-bootstrap`. Its trust is `aud = sts.amazonaws.com` and `sub = <sub prefix>:environment:bootstrap`, where the prefix is `repo:<owner>@<owner id>/<repo>@<repo id>` because this repo uses immutable OIDC subjects (check `gh api repos/<owner>/<repo>/actions/oidc/customization/sub`). Its permissions are S3 on the state bucket, and IAM create and update on `role/cloudbatch818-loria-*` and `policy/cloudbatch818-loria-*`, with an explicit Deny on IAM actions against its own role (its name matches the prefix, so the Allow would otherwise cover it).
2. Create the GitHub Environment `bootstrap` (required reviewer, deployment branch limited to `dev`) and set its variables `AWS_ROLE_ARN_BOOTSTRAP` and `AWS_REGION`.
3. Create the `dev` Environment the same way, then set `ALARM_EMAIL` (a secret: the address for alarm, budget and market activity emails) and, once `bootstrap-ci-roles` has made the roles, the role ARN variables the workflows read (`AWS_ROLE_ARN_TF`, `AWS_ROLE_ARN_DEPLOY`, `AWS_ROLE_ARN_DB`).
4. After `platform-create` first applies, store the runner's GitHub token (see "How the pieces fit").

Because the bootstrap role can mint roles it is effectively admin; the pinned `sub`, the reviewer gate and a `workflow_dispatch`-only trigger are its controls. Terraform never manages the OIDC provider or this role.

## Stacks

| Stack | State key | What it holds | Workflows |
| --- | --- | --- | --- |
| `bootstrap/` | `bootstrap/terraform.tfstate` | The CI roles: `tf-dev`, `deploy-dev` and `db-dev`, with their policies | `bootstrap-ci-roles.yml` |
| `envs/dev/platform/` | `dev/platform/terraform.tfstate` | Network, ECR, EKS, data stores, events, the in-VPC runner, the workload roles, the alarms, Container Insights and the Alertmanager role | `platform-create.yml`, `platform-destroy.yml` |
| `envs/dev/cluster-addons/` | `dev/cluster-addons/terraform.tfstate` | The `retail` namespace, the AWS Load Balancer Controller, External Secrets Operator, the `ClusterSecretStore`, their Pod Identity roles, and the RBAC the deploy role needs, and the Role that lets Prometheus list pods. Runs on the in-VPC runner because the cluster API is private | `addons-create.yml`, `addons-destroy.yml` |
| `envs/dev/dns/` | `dev/dns/terraform.tfstate` | The public ACM certificate for `dev.<domain>` and `internal.dev.<domain>`, its DNS validation records in the domain's existing Route 53 zone (read, never created here), and the private zone for the internal name, attached to the VPC. Needs `DEV_DOMAIN`; depends on the platform stack only for the VPC | `dns-create.yml`, `dns-destroy.yml` |
| `envs/dev/alb-dns/` | `dev/alb-dns/terraform.tfstate` | The alias records pointing the two names at the two ALBs. Separate because the ALBs are created by the load balancer controller after the platform stack; the workflow looks up each ALB's DNS name and zone id and passes them in, and an ALB that does not exist gets no record. Apply again after an ALB is recreated | `alb-dns-create.yml`, `alb-dns-destroy.yml` |
| `envs/dev/alb-alarms/` | `dev/alb-alarms/terraform.tfstate` | The ALB's 5xx-rate and p95-latency alarms. Separate because the ALB does not exist when the platform stack is planned; the ALB's identifier and the SNS topic are passed in or derived from a name, so it destroys cleanly after the ALB is gone | `alarms-create.yml`, `alarms-destroy.yml` |

The OIDC provider and the `cloudbatch818-loria-retail-bootstrap` role are created by hand once and never managed here; Terraform reads the provider with a `data` source. The domain itself is registered by hand in the Route 53 console and is not managed here either: the `dns` stack only reads its hosted zone, so no destroy can remove the domain's name servers. Steps and order: `docs/runbooks/https-and-domain.md`.

## Modules

| Module | Purpose |
| --- | --- |
| `network/` | VPC over 3 AZs: public, private-app (/20) and private-data subnets; one NAT in dev; S3 and DynamoDB gateway endpoints; interface endpoints |
| `ecr/` | `loria-retail/<name>` repositories: immutable tags, scan on push, keep 30 |
| `eks/` | Private-endpoint cluster, secrets KMS key, access entries, two-node AL2023 arm64 managed node group, add-ons |
| `data/` | RDS for PostgreSQL 17, ElastiCache for Valkey (TLS), the three DynamoDB tables, one KMS key |
| `events/` | The EventBridge bus, three queue routing rules, queues with DLQs (SSE, `aws:SourceArn` queue policies), the 7-day archive, and two Lambdas, each with its log group, role, dead-letter queue, rule, target and invoke permission: low-stock-alert, and market-activity-email with its SES identity (only when `ALARM_EMAIL` is set) |
| `runners/` | One ephemeral in-VPC GitHub runner (label `retail-vpc`): launch template, Auto Scaling group of one, instance role, security group, and the empty Secrets Manager secret for its token |
| `monitoring/` | One SNS topic and 17 CloudWatch alarms on AWS's own metrics: each dead-letter queue above 0 (the three plus the Lambda's), the oldest message in each queue over 120 s, EventBridge `FailedInvocations` per rule, Lambda errors, and RDS CPU, connections, freeable memory, free storage and transaction-ID wraparound. With an address, an email subscription and a monthly Budgets alert |
| `pod-identity-role/` | One IAM role for one Kubernetes service account through EKS Pod Identity, plus the association |
| `github-oidc/` | One IAM role trusting one exact GitHub OIDC `sub` |

## State, names and IAM scope

State is in `loria-retail-tfstate-<account-id>-<region>`, created by `bootstrap-state-bucket.yml`, with native locking. `cloudbatch818-loria-retail-tf-<env>` can touch only `<env>/*`.

Everything created is prefixed `loria-` (bucket, VPC, cluster `loria-retail-dev`, repositories `loria-retail/<name>`, queues, tables, ALBs). IAM roles keep `cloudbatch818-loria-`, the only prefix the manual bootstrap role may manage. CI roles are `cloudbatch818-loria-retail-<name>`; roles the stacks create (workload, cluster, node, runner, add-on) are `cloudbatch818-loria-retail-<env>-*`, the only IAM prefix `tf-<env>` may manage, so it cannot edit the CI roles or the bootstrap role.

## How the pieces fit

- **The cluster API is private.** The runner's security group is allowed into the cluster security group on 443. Anything that talks to Kubernetes (`cluster-addons`, the deploy, the seed) runs on that runner.
- **The runner registers with the repository named by `github_repository`** (`envs/dev/platform/variables.tf`, currently `loriamichaelj/cloud-punks`). Rename the repository and the runner can no longer get a registration token, and every job that needs it waits for ever; change the default and apply `platform-create`. The Auto Scaling group follows the launch template's version number, so that change replaces the instance.
- **The runner needs one manual step** after `platform-create` first applies it: create a fine-grained personal access token for the repository with *Administration: read and write*, and store it as the **plaintext** value of the secret `loria-retail-dev-runner-github-token` (the `runner_github_token_secret` output). The instance retries every 30 seconds until the secret has a value, then registers. Terraform never sees the token. Also set Settings, Actions, General, "Approval for running fork pull request workflows" to *Require approval for all outside collaborators*: self-hosted runners in a public repo must never run fork code, and every workflow that targets `retail-vpc` is `workflow_dispatch` only.
- **Workload roles** (`envs/dev/platform/workload-roles.tf`) give each AWS-calling service account its own queue, tables and the bus, and nothing else. A service account is named after its Helm release. The product service, order API and UI call no AWS service, so they have none. The tables use a customer-managed key, so those roles also hold the key permissions, limited to use through DynamoDB.
- **The deploy role** has `AmazonEKSEditPolicy` in `retail`, which does not cover custom resources. Its access entry is in the Kubernetes group `retail-deployers`, and `cluster-addons` binds that group to a Role allowing `externalsecrets` in `retail` only. Apply `platform-create` first (the group), then `addons-create` (the Role and binding).
- **`cluster-addons`** uses the `hashicorp/helm` and `hashicorp/kubernetes` providers (DESIGN.md section 13 calls for them) with pinned charts: AWS Load Balancer Controller 3.5.0, whose upstream IAM policy is vendored as `lbc-iam-policy.json`, and External Secrets Operator 2.11.0. The `ClusterSecretStore` goes in through a tiny local chart, `deploy/helm/secret-store`, installed after the operator: it is a custom resource, and a `kubernetes_manifest` would fail to plan on a freshly built cluster whose CRD does not exist yet.
- **Databases and seed.** `scripts/db_init.py` (`app-database.yml`) creates `product_db`, `order_db`, their owner and app roles and the four passwords; `local/seed/seed.py` (`app-seed.yml`) loads the catalog and stock. Both run on the runner as the `db` role. The platform stack lets the runner's security group reach PostgreSQL on 5432 for them, and the bootstrap stack creates the role (`AWS_ROLE_ARN_DB`, a variable on the `dev` Environment). The four secrets survive `platform-destroy` and are reused by a rebuild.
- **The Lambdas** (`modules/events/lambda.tf` and `market_email.tf`) read `dist/low-stock-alert.zip` and `dist/market-activity-email.zip`, which `scripts/package_lambda.py` builds. The platform workflows run it before `plan` and again before `apply` (and before the destroy pair), because the saved plan is applied on a different machine; the zip is byte-identical every time, so the plan's hash still matches. No `archive` provider. The functions are Python 3.13 on arm64. The low-stock function calls no AWS API: its role can only write its own logs and send to its dead-letter queue. The market-activity-email role may also send mail through SES as its one identity (`ses:SendRawEmail`); the apply role needs `ses:*` for the identity, granted by `bootstrap-ci-roles`. The deploy role may read that log group, for the acceptance test.
- **The DynamoDB tables** are `loria-inventory`, `loria-inventory-reservations` and `loria-notifications`. The services read the names from `INVENTORY_TABLE`, `RESERVATIONS_TABLE` and `NOTIFICATIONS_TABLE` (the defaults are the local names).
- **Dev RDS can be destroyed:** deletion protection is off and there is no final snapshot (`db_deletion_protection` and `db_skip_final_snapshot`). Turn both around for prod.
- **Two nodes** (`node_desired_size`). One m7g.large allows about 29 pods and 1930m CPU, which one node could not hold with Container Insights, Prometheus and Grafana; `cluster-capacity.yml` shows the headroom. Terraform sets the count.
- **Container Insights** (`envs/dev/platform/observability.tf`): the `amazon-cloudwatch-observability` EKS add-on (CloudWatch agent, Fluent Bit, operator), a Pod Identity role for the `cloudwatch-agent` service account, the four `/aws/containerinsights/<cluster>/*` log groups with 7-day retention (`log_retention_days`), and a saved Logs Insights query, `retail/trace-a-correlation-id`. The same file holds the `alertmanager` Pod Identity role: `sns:Publish` on the alarm topic and use of its key, so the monitoring chart's Alertmanager can send Prometheus alerts to it. The deploy role may run Logs Insights queries on the application group only, so the acceptance suite can trace an order.

## Checks

`pr.yml` runs `terraform fmt -check`, `validate` for the three stacks, tflint (`.tflint.hcl`, with the AWS ruleset) and Checkov on every pull request. Checkov exceptions are inline `#checkov:skip=ID:reason` lines next to the resource; Checkov resolves modules with the caller's variables, so run it over `envs/` as well as `modules/`. There is no `terraform plan` on pull requests.

## Alarms and the budget

The `monitoring` module is applied by `platform-create.yml`. Two things come first: run `bootstrap-ci-roles.yml` once so the `tf-dev` role may manage Budgets (`budgets:*`), and set the `dev` **environment secret** `ALARM_EMAIL` to the address that should hear about alarms (a secret, so it is masked in logs and never in the repository). Without the secret the topic and alarms are still created, with no subscription and no budget. After the first apply AWS emails a confirmation link to that address; click it, or nothing is delivered. The budget is limited to resources tagged `Project=retail-platform`, so the `Project` cost-allocation tag must be activated in Billing, Cost allocation tags (AWS shows the tag there only after it has seen it on a resource, and activation can take a day); until then the budget sees no cost. Thresholds are variables of the module.

The ALB alarms (5xx rate, p95 `TargetResponseTime`) are the `alb-alarms` stack. The controller creates the ALB from the Ingress, after the platform stack, and AWS invents the last part of its CloudWatch dimension (`app/<name>/<id>`), so `alarms-create.yml` looks the ALB up by name (`loria-retail-dev`) and passes the dimension in as `TF_VAR_alb_arn_suffix`; the topic's ARN is derived from the platform stack's naming. A data source would have broken the first plan and the destroy. Pod-restart, outbox-age and `orders_stuck` alerts are Prometheus rules in `deploy/helm/monitoring`, not CloudWatch alarms.

## Known gaps and choices to revisit

- ECR uses basic scan-on-push, not Inspector enhanced scanning. Enhanced needs Inspector enabled and `inspector2` permissions the apply role does not have.
- EKS add-on versions are not pinned (`addon_versions` is empty, so EKS picks its default for the cluster version), and RDS runs `engine_version = "17"`, so AWS picks the minor. Copy what the apply chose into the variables.
- Interface endpoints (about $7.30 per endpoint per AZ per month) sit in one AZ in dev. Set `interface_endpoint_services = []` to drop them and send that traffic through the NAT.
- Valkey has TLS, encryption at rest and a security-group limit, but no AUTH token: generating one hands the secret to Terraform and into state.
- TLS ends at the ALB: the hop to the pods and the calls between services are plain HTTP inside the VPC. The internal ALB also keeps port 80 (the deploy's readiness check and the acceptance suite reach it by its own name). HSTS is not set.
- None of the three teardown workflows has been run yet.
