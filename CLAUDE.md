# CLAUDE.md
Source of truth: docs/DESIGN.md. If code and doc disagree, stop and ask; do not silently diverge.

## Workflow
- Work one milestone (M0–M9) at a time. Finish with: make lint test (and itest/e2e when the milestone says so).
- Stop after each milestone with a summary of what changed, what was verified, and any deviation from DESIGN.md.
- Ask before adding a dependency, a service, a table, an event type, or changing an API contract.

## Must
- Domain code has no I/O imports (boto3, sqlalchemy, httpx, redis).
- Every consumer is idempotent on event_id; dedupe happens in the same transaction as the business write.
- Order events go through the outbox. Never call PutEvents from a request handler.
- Money: Decimal, strings in JSON. NUMERIC(10,2) for prices, NUMERIC(12,2) for order totals. IDs: ULID.
- AWS clients are built from env only; no endpoint URLs or credentials in code.
- Cloud AWS access exists only through GitHub Actions OIDC: workflows assume a role by ARN (stored as a GitHub variable, not a secret) with `permissions: id-token: write` and least-privilege per-purpose roles.
- Workflows that touch EKS run on the ephemeral self-hosted runners in the VPC; everything else runs on GitHub-hosted runners.
- Liveness checks nothing external. Readiness checks required stores only.
- Structured JSON logs with correlation_id; metric labels use route templates.
- Migrations: Alembic, backward compatible, run via the migrate command only.

## Must not
- Commit secrets or .env. Use .env.example.
- Cache inventory/stock data.
- Use :latest image tags anywhere (Compose, CI, or Helm values).
- Use KEYS * in Valkey, floats for money, or bare except.
- Add Kafka, a service mesh, a UI, auth, payments, or GitOps tooling.
- Write Helm before M8 is done, or Terraform / GitHub Actions before M9 is done.
- Run kubectl or helm without an explicit --context; local work always targets the orbstack context.
- Use, request, create or store AWS credentials (no `aws configure`, access keys, or AWS_* secrets in GitHub).
- Run terraform plan/apply, aws, kubectl or helm against AWS/EKS from the laptop. Locally only: terraform fmt/validate (`init -backend=false`), tflint, checkov, helm lint, kubeconform.
- Manage the OIDC provider or the `gha-bootstrap` role in Terraform (created by hand; Terraform reads the provider via a data source).
- Run self-hosted runners for fork PRs, or for any job that is not a deploy/drill/e2e job on main or an approved environment.
