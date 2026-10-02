# Workflows

Every workflow is independent: none calls another, each has its own concurrency group, and each assumes only the role its environment allows. Every workflow gets AWS access only through OIDC role assumption; role ARNs and `AWS_REGION` are GitHub Environment variables.

| Workflow | Trigger | Environment | Role (variable) | Concurrency group |
| --- | --- | --- | --- | --- |
| `bootstrap-state-bucket.yml` | `workflow_dispatch` | `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) | `bootstrap-state-bucket` |
| `bootstrap-ci-roles.yml` | `workflow_dispatch` | `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) | `bootstrap-ci-roles` |
| `platform-create.yml` | `workflow_dispatch` with an `action` choice: `plan` (print the plan) or `apply` (plan, then apply after a second approval) | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `platform-destroy.yml` | `workflow_dispatch` (a saved `plan -destroy`, then a second approval to apply it) | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `app-images.yml` | `workflow_dispatch` (builds the five images for arm64 and pushes `sha-<git sha>` to ECR) | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-images` |

## Run order

1. `bootstrap-state-bucket.yml`: creates `loria-retail-tfstate-<account-id>-<region>`. Safe to run again.
2. `bootstrap-ci-roles.yml`: creates the CI roles. Fails early if the bucket is missing.
3. `platform-create.yml`: the network, ECR repositories and EKS cluster. Run `plan` first.
4. `app-images.yml`: needs the ECR repositories from `platform-create`. Pushes images; deploys nothing.
5. `platform-destroy.yml`: removes the platform stack when the environment is idle. The bucket and the CI roles stay.

`platform-create` and `platform-destroy` share a group so they never touch the stack at once.

`app-deploy.yml` comes later, once the runners and cluster add-ons exist. Only the `dev` environment exists for now.
