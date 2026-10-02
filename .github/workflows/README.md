# Workflows

Every workflow is independent: none calls another, each has its own concurrency group, and each assumes only the role its environment allows. Every workflow gets AWS access only through OIDC role assumption; role ARNs and `AWS_REGION` are GitHub Environment variables.

| Workflow | Trigger | Environment | Role (variable) | Concurrency group |
| --- | --- | --- | --- | --- |
| `bootstrap-state-bucket.yml` | `workflow_dispatch` | `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) | `bootstrap-state-bucket` |
| `bootstrap-ci-roles.yml` | `workflow_dispatch` | `bootstrap` | `cloudbatch818-loria-retail-bootstrap` (`AWS_ROLE_ARN_BOOTSTRAP`) | `bootstrap-ci-roles` |
| `platform-create.yml` | `workflow_dispatch` with an `action` choice: `plan` (print the plan) or `apply` (plan, then apply after a second approval) | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `platform-destroy.yml` | `workflow_dispatch` (a saved `plan -destroy`, then a second approval to apply it) | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `addons-create.yml` | `workflow_dispatch` with an `action` choice: `plan` or `apply` (plan, then apply after a second approval). Runs on the `retail-vpc` runner | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `addons-destroy.yml` | `workflow_dispatch` (a saved `plan -destroy`, then a second approval). Runs on the `retail-vpc` runner | `dev` | `cloudbatch818-loria-retail-tf-dev` (`AWS_ROLE_ARN_TF`) | `platform-dev` |
| `app-images.yml` | `workflow_dispatch`. Publishes: builds the five arm64 images and pushes `sha-<git sha>` to ECR (approval) | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |
| `app-build.yml` | `workflow_dispatch`. The CI check, no AWS and no approval. Jobs: `prepare`, `test` (`make lint test`), `build` (builds the five images, pushes nothing), `notify` | none | none | `app-dev` |
| `app-deploy.yml` | `workflow_dispatch` with an optional image `tag` (default `sha-<this commit>`). Jobs: `deploy` (checks the images exist, Helm on the runners, e2e; approval), `notify` | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |
| `app-destroy.yml` | `workflow_dispatch` with a required `tag` (an image tag, or `all`) and an optional `uninstall_releases` (off by default; needs the runners) | `dev` | `cloudbatch818-loria-retail-deploy-dev` (`AWS_ROLE_ARN_DEPLOY`) | `app-dev` |

## Run order

1. `bootstrap-state-bucket.yml`: creates `loria-retail-tfstate-<account-id>-<region>`. Safe to run again.
2. `bootstrap-ci-roles.yml`: creates the CI roles. Fails early if the bucket is missing.
3. `platform-create.yml`: the network, ECR repositories, EKS cluster, data stores, queues and the runner. Run `plan` first. Then store the runner's GitHub token (see `infra/terraform/README.md`).
4. `addons-create.yml`: on the runner, the `retail` namespace, the AWS Load Balancer Controller and External Secrets Operator.
5. `app-build.yml`: lint, unit tests and a build of every image. Pushes nothing and needs no AWS, so it can run any time.
6. `app-images.yml`: pushes the images to ECR. Needs the repositories from `platform-create`.
7. `app-deploy.yml`: deploys a pushed tag to the cluster. Not runnable yet (see below).

Tearing down, in this order:

1. `app-destroy.yml`: removes the app (images, and the Helm releases once they exist). Needs the deploy role's `ecr:BatchDeleteImage`, which `bootstrap-ci-roles` grants.
2. `addons-destroy.yml`: removes the add-ons while the cluster still runs, so the load balancer controller can delete the ALBs it created.
3. `platform-destroy.yml`: removes the platform stack. It refuses to start while the addons stack still has resources. The bucket and the CI roles stay.

`platform-create`, `platform-destroy`, `addons-create` and `addons-destroy` share the group `platform-dev`, so none of them overlap. `app-images`, `app-build`, `app-deploy` and `app-destroy` share `app-dev`.

`app-build.yml` runs today. `app-deploy.yml` still needs `deploy/helm/values/values-*-dev.yaml` and a `DEV_BASE_URL` variable on `dev`, and a ClusterSecretStore for External Secrets; none exist yet. `app-build.yml` checks and `app-images.yml` publishes; they do not overlap. Only the `dev` environment exists for now.
