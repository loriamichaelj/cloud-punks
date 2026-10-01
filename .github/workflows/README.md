# Workflows

| Workflow | Trigger | Role (variable) |
| --- | --- | --- |
| `bootstrap.yml` | `workflow_dispatch`, environment `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) |

The rest come in Phase 3. Every workflow gets AWS access only through OIDC role assumption; role ARNs and `AWS_REGION` are GitHub Environment variables.
