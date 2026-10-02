# Workflows

| Workflow | Trigger | Role (variable) |
| --- | --- | --- |
| `state-bucket.yml` | `workflow_dispatch`, or called by `bootstrap.yml`; environment `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) |
| `bootstrap.yml` | `workflow_dispatch`, environment `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) |
| `infra.yml` | `pull_request` on `infra/**` (plan only); `workflow_dispatch` (separate `plan` and `apply` jobs, each approved), environment `dev` | `cloudbatch818-loria-tf-plan` (`AWS_ROLE_ARN_TF_PLAN`, repository variable); `cloudbatch818-loria-tf-apply-dev` (`AWS_ROLE_ARN_TF_APPLY`) |

The rest come in Phase 3. Every workflow gets AWS access only through OIDC role assumption; role ARNs and `AWS_REGION` are GitHub Environment variables.
