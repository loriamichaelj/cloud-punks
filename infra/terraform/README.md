# Terraform

Applied only from GitHub Actions (ADR-14). Locally: `terraform fmt`, `terraform init -backend=false` and `terraform validate`.

| Path | Purpose |
| --- | --- |
| `bootstrap/` | The `cloudbatch818-loria-*` roles for CI. State key `bootstrap/terraform.tfstate`. Run by `bootstrap-ci-roles.yml` |
| `envs/dev/platform/` | Dev network, ECR and EKS. State key `dev/platform/terraform.tfstate`. Created by `platform-create.yml`, removed by `platform-destroy.yml` |
| `modules/network/` | VPC over 3 AZs: public, private-app (/20) and private-data subnets, one NAT in dev, S3 and DynamoDB gateway endpoints, interface endpoints |
| `modules/ecr/` | `loria-retail/<service>` repositories: immutable tags, scan on push, keep 30 |
| `modules/eks/` | Private-endpoint cluster, secrets KMS key, access entries, one-node AL2023 arm64 managed node group, add-ons |
| `modules/github-oidc/` | One IAM role trusting one exact GitHub OIDC `sub`. Reads the hand-made OIDC provider with a `data` source |

State lives in `loria-retail-tfstate-<account-id>-<region>`, created by `bootstrap-state-bucket.yml`. Keys are `<stack>/terraform.tfstate` for `bootstrap` and `<env>/<stack>/terraform.tfstate` for environments; `cloudbatch818-loria-retail-tf-<env>` can touch only `<env>/*`.

CI role names start with `cloudbatch818-loria-retail-`, inside the `cloudbatch818-loria-*` the manual `cloudbatch818-loria-retail-bootstrap` role may manage. Roles the platform stacks create (workload, cluster, runner roles) use `cloudbatch818-loria-retail-<env>-*`, the only IAM prefix `cloudbatch818-loria-retail-tf-<env>` may manage.

Choices to revisit:

- ECR uses basic scan-on-push, not Inspector enhanced scanning (DESIGN.md says enhanced). Enhanced needs Inspector enabled and `inspector2` permissions the apply role does not have.
- Interface endpoints (about $7.30 per endpoint per AZ per month) sit in one AZ in dev. Set `interface_endpoint_services = []` to drop them and send that traffic through the NAT.
- EKS add-on versions are not pinned yet. `addon_versions` is empty, so EKS picks its default for the cluster version; copy the versions the first apply reports into the dev values.
- The cluster API is private-only. The runners module must add an ingress rule from the runner security group to the cluster security group on 443.

Naming: everything Terraform and the workflows create is prefixed `loria-` (state bucket, VPC, cluster `loria-retail-dev`, ECR repositories `loria-retail/<service>`, KMS alias, log group). IAM roles and policies are the exception and keep `cloudbatch818-loria-`, because that is the only prefix the manual bootstrap role may manage.
