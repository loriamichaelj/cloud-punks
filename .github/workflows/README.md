# Workflows

| Workflow | Trigger | Role (variable) |
| --- | --- | --- |
| `bootstrap.yml` | `workflow_dispatch`, environment `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) |
| `infra.yml` | `pull_request` on `infra/**` (plan only); `workflow_dispatch` (plan, then apply), environment `dev` | `cloudbatch818-tf-plan` (`AWS_ROLE_ARN_TF_PLAN`, repository variable); `cloudbatch818-tf-apply-dev` (`AWS_ROLE_ARN_TF_APPLY`) |

The rest come in Phase 3. Every workflow gets AWS access only through OIDC role assumption; role ARNs and `AWS_REGION` are GitHub Environment variables.
