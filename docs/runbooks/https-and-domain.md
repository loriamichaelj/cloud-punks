# HTTPS and the dev domain

How dev gets a name and a certificate, in the order to do it, and what to check when it does not work. The
design is DESIGN.md section 13 ("Network and names") and ADR-24. No step needs the AWS CLI or CloudShell: one
step is the Route 53 console, the rest are workflows.

**Status: written from the design and the code. None of it has been applied yet** (the Route 53 permission for
the Terraform role is the first step, below).

## What you end up with

- `https://dev.<domain>`: the viewer ALB (`app-expose`), reachable only from `DEV_VIEWER_CIDR`. Port 80 redirects.
- `https://internal.dev.<domain>`: the internal ALB, resolvable and reachable only inside the VPC. `app-deploy`
  checks it and reports in its run summary. Port 80 stays for the deploy's own checks.
- One public ACM certificate covers both names.

## Set it up

1. **Register the domain** in the Route 53 console (Registered domains, Register domains). It costs a yearly
   fee and renews itself. AWS emails the registrant: click the verification link within 15 days or the domain is
   suspended. Registering creates the public hosted zone; the stacks only read it.
2. **Set the `dev` environment variable `DEV_DOMAIN`** (GitHub, Settings, Environments, `dev`, Variables) to the
   registered domain, for example `example.com`. A variable, not a secret: the name is public in DNS anyway.
   Leave it unset and every workflow keeps serving plain HTTP, as before.
3. **`bootstrap-ci-roles`**, once: the `tf-dev` role gains `route53:*`.
4. **`dns-create`** (`plan`, then `apply`): the certificate, its validation records and the private zone. The
   apply waits until ACM has issued the certificate.
5. **`app-deploy`**: the `gateway` release gets its `tls` host and both listeners. If `app-expose` is installed
   it is refreshed the same way. On the first deploy the HTTPS check in the run summary says "not ready": the name
   does not exist until the next step.
6. **`app-expose`** with `expose`, if the browser address is wanted.
7. **`alb-dns-create`** (`plan`, then `apply`): the alias records for whichever ALBs exist.
8. **`app-deploy` again**: its HTTPS check should now say `answered 200 with a valid certificate`. Open
   `https://dev.<domain>` from the `DEV_VIEWER_CIDR` address.

Run `alb-dns-create` again whenever an ALB is recreated: `app-expose` with `remove` then `expose` gives the viewer
ALB a new DNS name, and the record keeps pointing at the old one until the stack is applied.

## Take it down

`alb-dns-destroy`, then `dns-destroy`, then the usual order (`.github/workflows/README.md`). `platform-destroy`
refuses while either stack has resources. The domain and its zone are never touched; the yearly registration
fee continues until you let it lapse in the console.

## When it does not work

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `dns-create` apply sits at "Still creating" on the certificate validation | The validation records are not visible in public DNS: the zone the stack found is not the one the domain delegates to | In the console, compare the domain's name servers with its hosted zone's; they must match |
| `dns-create` fails with an access error on Route 53 | `bootstrap-ci-roles` has not run since the `route53:*` grant | Run it |
| `app-deploy` finishes but the ALB never gets an address, and `describe ingress` in its log says no certificate was found | `app-deploy` ran before the certificate was ISSUED, or `DEV_DOMAIN` differs from the one `dns-create` used | Check the certificate status in the ACM console (Issued); run `dns-create` again; deploy again |
| The HTTPS check says `answered 000` or a DNS error | `alb-dns-create` has not run since the ALB was created, or the runner has not picked up the private zone yet | Run `alb-dns-create`; wait a minute; deploy again |
| The browser warns about the certificate on the viewer ALB | You opened the ALB's own `...elb.amazonaws.com` name, which the certificate does not cover | Use `https://dev.<domain>` |
| The viewer name times out | The ALB's security group admits only `DEV_VIEWER_CIDR`, and your address changed | Update the secret and run `app-expose` again (the DNS record does not change) |
| The viewer name gives a DNS error | The viewer ALB was removed, or recreated and the record is stale | `app-expose` with `expose`, then `alb-dns-create` |
