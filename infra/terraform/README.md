# Terraform

Applied only from GitHub Actions (ADR-14). Locally: `terraform fmt`, `terraform init -backend=false` and `terraform validate`.

| Path | Purpose |
| --- | --- |
| `bootstrap/` | The `cloudbatch818-*` roles for CI. State key `bootstrap/terraform.tfstate`. Run by `bootstrap.yml` |
| `modules/github-oidc/` | One IAM role trusting one exact GitHub OIDC `sub`. Reads the hand-made OIDC provider with a `data` source |

State lives in `retail-tfstate-<account-id>-<region>`, created by `bootstrap.yml`. Keys are `<stack>/terraform.tfstate` for `bootstrap` and `<env>/<stack>/terraform.tfstate` for environments; `cloudbatch818-tf-apply-<env>` can touch only `<env>/*`.

Role names all start with `cloudbatch818-`, the only prefix the manual `cloudbatch818-loria-retail-bootstrap` role may manage. Roles the platform stacks create (workload, cluster, runner roles) use `cloudbatch818-retail-*`, the only IAM prefix `cloudbatch818-tf-apply-<env>` may manage.
