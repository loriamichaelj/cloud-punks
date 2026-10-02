# Workflows

| Workflow | Trigger | Role (variable) |
| --- | --- | --- |
| `state-bucket.yml` | `workflow_dispatch`, or called by `bootstrap.yml`; environment `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) |
| `bootstrap.yml` | `workflow_dispatch`, environment `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) |
| `infra-create.yml` | `pull_request` on `infra/**` (plan only); `workflow_dispatch` with an `action` choice: `plan` (print the plan) or `apply` (plan, then apply after a second approval), environment `dev` | `cloudbatch818-loria-retail-tf-plan-dev` (`AWS_ROLE_ARN_TF_PLAN`, repository variable); `cloudbatch818-loria-retail-tf-apply-dev` (`AWS_ROLE_ARN_TF_APPLY`) |
| `infra-destroy.yml` | `workflow_dispatch`, environment `dev` (a saved `plan -destroy`, then a second approval to apply it) | `cloudbatch818-loria-retail-tf-apply-dev` (`AWS_ROLE_ARN_TF_APPLY`) |

The rest come in Phase 3. Every workflow gets AWS access only through OIDC role assumption; role ARNs and `AWS_REGION` are GitHub Environment variables.
