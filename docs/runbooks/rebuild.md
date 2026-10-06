# Rebuild dev after a teardown

How to take dev down when it is idle and bring it back, in the order that works, with the manual steps that
are easy to miss. Every step is a workflow except where it says otherwise; no laptop has AWS access
(ADR-14). The workflows themselves are described in `.github/workflows/README.md`.

**Status: the teardown below was run end to end on 6 Oct 2026 and every stage succeeded. The rebuild has not
been run yet.** It is written from the code and from that teardown, so treat a step that does not match what you
see as a runbook bug and fix it. Nothing outside Terraform state was checked after the teardown (see
"After the teardown").

## What a teardown keeps and what it loses

Kept, so a rebuild starts from them:

- The state bucket, the CI roles, the OIDC provider and the `cloudbatch818-loria-retail-bootstrap` role. Do not
  run `bootstrap-state-bucket` or `bootstrap-ci-roles` again unless you changed them.
- The `dev` and `bootstrap` GitHub Environments with their variables and secrets (`AWS_REGION`, the role ARNs,
  `DEV_DOMAIN`, `DEV_VIEWER_CIDR`, `ALARM_EMAIL`), and the personal access token for the runner (only its copy in
  AWS is lost, see step 2).
- The domain and its public hosted zone. No stack manages them.
- The four app-role secrets in Secrets Manager (`loria-retail-dev/<service>-<owner|app>-db`). `app-database`
  reuses their passwords and sets the new database's roles to match.
- The `Project` cost-allocation tag activation in Billing.

Lost, because dev is disposable:

- **All data.** RDS has no final snapshot, so the catalog, orders, listings, bids and the activity feed are gone;
  so are the DynamoDB stock and reservations, the notifications table, Valkey and the event archive. A rebuilt
  market starts clean: `app-seed` loads the 100 CloudPunks and one unit of stock each, and `app-reset` is not
  needed.
- **Every image in ECR.** The repositories are empty, so nothing deploys until `app-prepare` builds again.
- The runner's token secret (its value, not the PAT), the certificate and private zone, the SES identity and
  the SNS subscription. The last two need a click in an email again (step 12).

## Take it down

Run these one at a time and read each plan before the second approval. The Terraform stages share the group
`platform-dev`, which keeps one run waiting and cancels the rest, so do not queue several.

| # | Workflow | Inputs | What it removes | Took (6 Oct) |
| --- | --- | --- | --- | --- |
| 1 | `app-destroy` | `tag` = `all`, `uninstall_releases` on | Every Helm release in `retail` (13), which deletes both ALBs while the load balancer controller still runs, then every image in the five ECR repositories (90) | about 2 min |
| 2 | `alb-dns-destroy` | none | The two alias records | about 2 min |
| 3 | `dns-destroy` | none | The certificate, its validation records and the private zone (5 resources). The domain and its public zone are untouched | about 3 min |
| 4 | `alarms-destroy` | none | The two ALB alarms. It finds no ALB and plans with a placeholder, which is expected | about 16 min, 15 of them before its plan started |
| 5 | `addons-destroy` | none | The load balancer controller, External Secrets Operator, the `retail` namespace, the RBAC and the two Pod Identity roles (14 resources). Runs on the `retail-vpc` runner | about 2 min |
| 6 | `platform-destroy` | none | The rest: network, EKS, RDS, Valkey, DynamoDB, queues and bus, Lambdas, ECR, KMS, the runner (184 resources) | about 11 min |

The time column is the run's own, from start to finish. Where a run took longer, the rest was waiting for an
approval.

Two choices in that order matter:

- **`app-destroy` goes first, with both inputs.** The certificate is attached to the ALB listeners, and ACM
  refuses to delete a certificate that a listener still uses, so `dns-destroy` has to come after the ALBs are
  gone. (`.github/workflows/README.md` lists `dns-destroy` first. The order above is the one that ran; the other
  order was not tried.) `uninstall_releases` is what deletes the Ingresses, and so the ALBs, while the controller
  can still do it. `tag=all` empties ECR: the repositories are not force-deleted, and `platform-destroy` does
  not check them, so it would stop on a repository that still holds images.
- **`platform-destroy` refuses to start** while the alarms, alias, DNS or add-ons stacks still hold resources.
  That check reads Terraform state only. It cannot see an ALB or an image.

### After the teardown

Nothing outside Terraform state has been checked yet. Before counting on the bill dropping to its floor, look in
the console for what a destroy can leave behind: load balancers and target groups named `k8s-*`, network
interfaces and security groups in the old VPC (none should remain), the log groups under `/aws/` for the
cluster, the Lambdas and Container Insights, and the KMS keys, which wait out their deletion window.

## Bring it back

Start from a clean checkout of `dev`. Each Terraform stage is a `plan` run first, read, then `apply`.

1. **`platform-create`**, `plan`, then `apply`. This is the long one: EKS, RDS and Valkey. Its run summary ends
   with the Terraform outputs; keep it open, step 6 needs two of them (`db_endpoint`, `cache_url`).
2. **Store the runner's GitHub token.** The secret `loria-retail-dev-runner-github-token` was deleted with the
   stack and has been recreated empty. Put the personal access token in it as the plaintext value, exactly as
   `infra/terraform/README.md` describes (*Administration: read and write* on the repository). The instance
   retries every 30 seconds, so within a minute or two the runner `retail-vpc` appears under Settings, Actions,
   Runners. Do not go on until it shows as idle: every Kubernetes step below waits for it for ever.
3. **`dns-create`**, `plan`, then `apply`, if `DEV_DOMAIN` is set. It needs the new VPC (for the private zone)
   and must finish, with the certificate ISSUED, before the first `app-deploy`.
4. **`addons-create`**, `plan`, then `apply`. On the runner. Its first check is that the runner can reach the
   private cluster API.
5. **`app-database`**. Creates `product_db` and `order_db` and their roles on the new instance and reuses the four
   secrets (its summary says `reused` for each).
6. **Refresh the two endpoints that are written into the repository**, from step 1's outputs:
   - `CACHE_URL` in `deploy/helm/values/values-common-dev.yaml` is `cache_url`. **It changes with every rebuild**:
     the endpoint contains an identifier ElastiCache invents for the new replication group.
   - `DB_HOST` appears in `values-product-service-dev.yaml`, `values-order-service-dev.yaml`,
     `values-order-relay-dev.yaml` and `values-order-consumer-dev.yaml` and is `db_endpoint`. It should not
     change (the same instance name in the same account and region gives the same host name), so this is a check,
     not an edit: compare `grep -rn DB_HOST deploy/helm/values/*-dev.yaml` with the output.

   Commit and push the change on `dev` (the owner does this; it is not part of any workflow). Do it **before**
   step 7: images are tagged `sha-<commit>`, and `app-deploy` defaults to the commit it runs from, so building
   from an older commit would leave you deploying with a tag you have to type.
7. **`app-prepare`**: `prepare`, `test` and `build` (approval), then `verify` (approval). ECR is empty, so
   `build` pushes all five images. The run summary starts with the tag for `app-deploy`.
8. **`app-deploy`**, with that tag or empty. This installs the `secrets` release first, then the eight processes,
   `ui` and `gateway`, then `monitoring`, and runs the acceptance suite. **Its e2e step is red this time**: the
   schema is created by `product-service`'s migration hook during this deploy and the catalog is empty. That is
   expected.
9. **`app-seed`**. Loads the 100 CloudPunks and their stock.
10. **`app-deploy` again**. The acceptance suite should now pass (17 of 17 in the cloud).
11. Optional, in this order:
    1. **`app-expose`** with `expose`, then open the address in its run summary. It needs `DEV_VIEWER_CIDR`.
    2. **`alb-dns-create`**, `plan`, then `apply`, if `DEV_DOMAIN` is set. The ALBs are new, so the records must be
       rewritten; this is also why it comes after `app-expose`.
    3. **`app-deploy` once more**. Its HTTPS check should say `answered 200 with a valid certificate`.
    4. **`alarms-create`**, `plan`, then `apply`. It looks the new ALB up by name, so it needs the first
       `app-deploy`.
12. **Click the two emails** AWS sends to the `ALARM_EMAIL` address: the SES address verification (nothing is
    delivered until you do) and the SNS subscription confirmation for the alarm topic. Both were deleted with
    the stacks and come back unconfirmed. Without the first, market activity emails are not sent; without the
    second, no alarm reaches you.

### Checking it is up

- `app-deploy`'s last run is green, including the e2e step.
- `app-prepare`'s `verify` job reports what runs equals what ECR holds.
- `cluster-capacity` shows both nodes, every pod Ready and headroom left.
- The browser address (and `https://dev.<domain>` with a domain) shows the CloudPunks market.

## When it does not work

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `addons-create` waits for a runner, or its first check says the runner cannot reach the cluster API | The token secret is empty or wrong, so the runner never registered; or the runner is still starting | Store the token (step 2) and check Settings, Actions, Runners. If the repository was renamed, see `https-and-domain.md`'s last row |
| Pods start but cannot reach the cache, or `app-deploy` waits on a release that never becomes ready | `CACHE_URL` still holds the old endpoint (step 6) | Fix the value, commit, then `app-prepare` and `app-deploy` from that commit |
| Pods cannot connect to the database | `DB_HOST` differs from the new `db_endpoint` | Fix the four values files, then as above |
| `app-deploy` stops at "images not found" | The tag was never built here, or it belongs to a commit before step 6 | Run `app-prepare` from the commit you are deploying and paste the tag it prints |
| `app-database` says a role or secret already exists with another shape | A secret from before the teardown holds something other than the JSON with a `password` key | Look at the named secret in Secrets Manager; `db_init.py` stops rather than overwrite it |
| `app-deploy` finishes but the ALB never gets an address | The certificate is not ISSUED yet, or `dns-create` has not run | `https-and-domain.md`, "When it does not work" |
| The e2e step is red after the second deploy | The catalog is empty or the seed did not finish | Run `app-seed` and check its summary, then deploy again |
| No emails arrive | The SES or SNS confirmation (step 12) is still waiting | Click the two links; check the spam folder for the first email |
| `platform-destroy` stops at its first step and names a workflow | That stack still holds resources | Run the named workflow first |
| `platform-destroy` fails deleting the VPC, a subnet or a security group | An ALB, target group or network interface made by the controller is still there | Find it in the console (`k8s-*`), delete it, run `platform-destroy` again; it picks up from state |
| `platform-destroy` fails on an ECR repository | It still holds images | Run `app-destroy` with `tag` = `all`, then `platform-destroy` again |
