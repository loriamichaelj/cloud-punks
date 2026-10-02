# Terraform

Applied only from GitHub Actions (ADR-14). Locally: `terraform fmt`, `terraform init -backend=false` and `terraform validate`.

| Path | Purpose |
| --- | --- |
| `bootstrap/` | The `cloudbatch818-loria-*` roles for CI. State key `bootstrap/terraform.tfstate`. Run by `bootstrap-ci-roles.yml` |
| `envs/dev/platform/` | Dev network, ECR and EKS. State key `dev/platform/terraform.tfstate`. Created by `platform-create.yml`, removed by `platform-destroy.yml` |
| `modules/network/` | VPC over 3 AZs: public, private-app (/20) and private-data subnets, one NAT in dev, S3 and DynamoDB gateway endpoints, interface endpoints |
| `modules/ecr/` | `loria-retail/<service>` repositories: immutable tags, scan on push, keep 30 |
| `modules/eks/` | Private-endpoint cluster, secrets KMS key, access entries, one-node AL2023 arm64 managed node group, add-ons |
| `modules/runners/` | One ephemeral in-VPC GitHub runner (label `retail-vpc`): launch template, Auto Scaling group of one, instance role, security group, the empty Secrets Manager secret for the PAT |
| `envs/dev/cluster-addons/` | The `retail` namespace, the AWS Load Balancer Controller and External Secrets Operator, with their Pod Identity roles. State key `dev/cluster-addons/terraform.tfstate`. Runs on the in-VPC runner (the cluster API is private): `addons-create.yml`, `addons-destroy.yml` |
| `modules/pod-identity-role/` | One IAM role for one Kubernetes service account through EKS Pod Identity, plus the association |
| `modules/events/` | EventBridge bus, the three routing rules, queues with DLQs (SSE, `aws:SourceArn` queue policies) and the 7-day archive |
| `modules/data/` | RDS for PostgreSQL 17, ElastiCache for Valkey (TLS), the three DynamoDB tables, one KMS key |
| `modules/github-oidc/` | One IAM role trusting one exact GitHub OIDC `sub`. Reads the hand-made OIDC provider with a `data` source |

State lives in `loria-retail-tfstate-<account-id>-<region>`, created by `bootstrap-state-bucket.yml`. Keys are `<stack>/terraform.tfstate` for `bootstrap` and `<env>/<stack>/terraform.tfstate` for environments; `cloudbatch818-loria-retail-tf-<env>` can touch only `<env>/*`.

CI role names start with `cloudbatch818-loria-retail-`, inside the `cloudbatch818-loria-*` the manual `cloudbatch818-loria-retail-bootstrap` role may manage. Roles the platform stacks create (workload, cluster, runner roles) use `cloudbatch818-loria-retail-<env>-*`, the only IAM prefix `cloudbatch818-loria-retail-tf-<env>` may manage.

Choices to revisit:

- ECR uses basic scan-on-push, not Inspector enhanced scanning (DESIGN.md says enhanced). Enhanced needs Inspector enabled and `inspector2` permissions the apply role does not have.
- Interface endpoints (about $7.30 per endpoint per AZ per month) sit in one AZ in dev. Set `interface_endpoint_services = []` to drop them and send that traffic through the NAT.
- EKS add-on versions are not pinned yet. `addon_versions` is empty, so EKS picks its default for the cluster version; copy the versions the first apply reports into the dev values.
- The cluster API is private-only. The runners module must add an ingress rule from the runner security group to the cluster security group on 443.

Naming: everything Terraform and the workflows create is prefixed `loria-` (state bucket, VPC, cluster `loria-retail-dev`, ECR repositories `loria-retail/<service>`, KMS alias, log group). IAM roles and policies are the exception and keep `cloudbatch818-loria-`, because that is the only prefix the manual bootstrap role may manage.
- Not in the `events` module yet: the `low-stock-alert` Lambda and its `to-low-stock` rule. Packaging the function needs the `hashicorp/archive` provider (a new dependency, so it waits for a decision).
- ElastiCache has no AUTH token yet. Generating one hands the secret to Terraform and into state; the cache is reachable only from the EKS cluster security group, with TLS and encryption at rest.
- RDS runs `engine_version = "17"`, so AWS picks the default 17.x minor. Pin the minor once the first apply shows it. `product_db`, `order_db` and the app roles inside them are created by the bootstrap migration, which also needs app-user secrets in Secrets Manager; neither exists yet.
- Dev RDS has deletion protection off and no final snapshot, so `platform-destroy` can remove it. DESIGN.md asks for protection: set `db_deletion_protection = true` for prod.
- The DynamoDB tables are named `loria-inventory`, `loria-inventory-reservations` and `loria-notifications`. The services read the names from `INVENTORY_TABLE`, `RESERVATIONS_TABLE` and `NOTIFICATIONS_TABLE` (defaults are the local names).
- The runner needs a one-time manual step after `platform-create` applies it. Create a fine-grained personal access token for this repository with *Administration: read and write*, then store it as the secret's value (the secret is named in the `runner_github_token_secret` output, `loria-retail-dev-runner-github-token`). The instance retries every 30 seconds until the secret has a value, then registers. Terraform never sees the token.
- Also set Settings > Actions > General > "Approval for running fork pull request workflows" to *Require approval for all outside collaborators*. Self-hosted runners in a public repo must never run fork code; the workflows that target `retail-vpc` run only on `workflow_dispatch`.
- The runner is the only instance that can reach the private cluster API from outside the cluster. Its security group is allowed into the cluster security group on 443.
- `cluster-addons` adds the `hashicorp/helm` and `hashicorp/kubernetes` providers (DESIGN.md section 13 already calls for them). Chart versions are pinned: AWS Load Balancer Controller 3.5.0 with its upstream IAM policy vendored as `lbc-iam-policy.json`, External Secrets Operator 2.11.0.
- The External Secrets `ClusterSecretStore` is not created here. It is a custom resource whose CRD exists only after the operator installs, so it comes with the dev Helm values.
- One node limits the pods: the add-ons plus the application releases must fit the m7g.large's pod limit (about 29 with the default VPC CNI). Check `kubectl get pods -A` after the first deploy.
- Dev has no ACM certificate or domain, so the first ingress is plain HTTP on an internal ALB.
