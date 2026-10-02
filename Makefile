SHELL := /bin/bash

SERVICES := product-service inventory-service order-service notification-service

# Compose must always read the repo-root .env; without --env-file it would read local/.env
# and ${VAR} interpolation would silently produce empty passwords (DESIGN.md section 10).
COMPOSE = docker compose --env-file .env -f local/docker-compose.yml

# down/reset/logs must work even when LOCALSTACK_AUTH_TOKEN is not set yet; Compose
# interpolates the whole file, and the token guard would otherwise refuse to tear down.
COMPOSE_NOAUTH = LOCALSTACK_AUTH_TOKEN=unused $(COMPOSE)

# Images are tagged dev-<git sha>, never :latest.
IMAGE_TAG ?= dev-$(shell git rev-parse --short HEAD 2>/dev/null || echo nogit)
export IMAGE_TAG

RUN = uv run --frozen --no-sync

.PHONY: help lock sync fmt lint test itest e2e drills drill-consumer-down drill-poison drill-duplicate drill-bus-down drill-cache-down drill-db-down dlq-peek dlq-redrive obs-up obs-down k8s-lint k8s-build k8s-build-multiarch k8s-secrets k8s-ingress k8s-deploy k8s-e2e k8s-resilience k8s-rollback k8s-down up down reset logs seed openapi ui-install ui-dev ui-types ui-lint ui-typecheck ui-test ui-build ui-e2e ui-types-check openapi-check

help:
	@echo "Targets: lock sync fmt lint test itest e2e up down reset logs s=<service> seed openapi ui-*"

.env:
	cp .env.example .env
	@echo "Created .env from .env.example (git-ignored). Set LOCALSTACK_AUTH_TOKEN before `make up`."

lock:
	uv lock

sync:
	uv sync --all-packages --locked

fmt: sync
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

# Every service's top-level package is named `app`, so mypy and pytest run once per service
# (separate processes and caches) instead of once over the whole workspace.
lint: sync
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy --config-file pyproject.toml --cache-dir .mypy_cache/common libs/common/retail_common
	@for s in $(SERVICES); do \
		echo "mypy $$s"; \
		$(RUN) mypy --config-file pyproject.toml --cache-dir .mypy_cache/$$s services/$$s/app || exit 1; \
	done
	$(RUN) mypy --config-file pyproject.toml --cache-dir .mypy_cache/functions functions/low-stock-alert/handler.py
	@$(MAKE) --no-print-directory openapi-check ui-types-check ui-lint ui-typecheck ui-build k8s-lint

test: sync
	@echo "pytest libs/common (coverage gate: 80%)"
	@$(RUN) pytest libs/common/tests -q --cov=retail_common --cov-report=term-missing:skip-covered --cov-fail-under=80
	@for s in $(SERVICES); do \
		echo "pytest $$s"; \
		PYTHONPATH=services/$$s $(RUN) pytest services/$$s/tests/unit -q || exit 1; \
	done
	@echo "pytest scripts"
	@PYTHONPATH=scripts $(RUN) pytest scripts/tests -q
	@echo "pytest functions/low-stock-alert"
	@$(RUN) pytest functions/low-stock-alert/tests -q
	@$(MAKE) --no-print-directory ui-test

# Integration tests run each service in-process against the real stores of the running stack
# (`make up` first). `--env-file .env` supplies the database passwords to the tests.
#
# The order relay tests need exclusive ownership of the outbox, so a running `order-relay`
# container is paused for the run and started again afterwards (even if a test fails).
itest: sync
	@relay_was_running=$$($(COMPOSE_NOAUTH) ps --status running --services 2>/dev/null | grep -c '^order-relay$$' || true); \
	if [ "$$relay_was_running" != "0" ]; then echo "pausing order-relay for the integration tests"; $(COMPOSE_NOAUTH) stop order-relay >/dev/null; fi; \
	status=0; \
	for s in $(SERVICES); do \
		if ls services/$$s/tests/integration/test_*.py >/dev/null 2>&1; then \
			echo "pytest integration $$s"; \
			PYTHONPATH=services/$$s:services/$$s/tests/integration $(RUN) --env-file .env \
				pytest services/$$s/tests/integration -q -m integration || { status=$$?; break; }; \
		fi; \
	done; \
	if [ "$$relay_was_running" != "0" ]; then echo "starting order-relay again"; $(COMPOSE_NOAUTH) start order-relay >/dev/null; fi; \
	exit $$status

# End-to-end acceptance test through the gateway against the running stack (`make up seed`
# first). E2E_COMPOSE lets the drills stop and start a consumer container.
e2e: sync
	E2E_COMPOSE="$(COMPOSE)" PYTHONPATH=tests/e2e $(RUN) pytest tests/e2e -q

# --- Failure drills (DESIGN.md section 11) --------------------------------------------------------
# Each drill breaks one thing in the running stack, checks detection and recovery, and puts the
# stack back even when it fails. `make e2e` runs all of them after the acceptance steps.
DRILL = E2E_COMPOSE="$(COMPOSE)" PYTHONPATH=tests/e2e $(RUN) pytest tests/e2e/test_drills.py -q

drills: sync
	$(DRILL)

drill-consumer-down drill-poison drill-duplicate drill-bus-down drill-cache-down drill-db-down: sync
	$(DRILL) -k "test_drill_$(subst -,_,$(patsubst drill-%,%,$@))"

# The DLQ tools talk to LocalStack only: endpoint and dummy credentials are set here, and a
# profile or session token in the shell is dropped, so they cannot reach a real account.
LOCAL_AWS = env -u AWS_PROFILE -u AWS_SESSION_TOKEN AWS_ENDPOINT_URL=http://localhost:4566 \
	AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1

# make dlq-peek q=inventory-order-events-dlq   (lists, takes nothing)
dlq-peek: sync
	@test -n "$(q)" || { echo "usage: make dlq-peek q=<queue>-dlq"; exit 2; }
	@$(LOCAL_AWS) $(RUN) python scripts/dlq.py peek $(q)

# make dlq-redrive q=inventory-order-events-dlq   (moves every message back to its source queue)
dlq-redrive: sync
	@test -n "$(q)" || { echo "usage: make dlq-redrive q=<queue>-dlq"; exit 2; }
	@$(LOCAL_AWS) $(RUN) python scripts/dlq.py redrive $(q)

# --- Local Kubernetes on OrbStack (DESIGN.md section 10, M10) ---------------------------------
# PostgreSQL, Valkey and LocalStack stay in Compose on the Mac (like managed services on EKS);
# the processes run in namespace `retail` from the chart in deploy/helm. Every kubectl and helm
# call names --context orbstack, so a command can never land on an EKS cluster that happens to
# be the current context.
K8S_CONTEXT := orbstack
KUBECTL = kubectl --context $(K8S_CONTEXT) -n retail
HELM = helm --kube-context $(K8S_CONTEXT) -n retail
CHART = deploy/helm/retail-service
HV = deploy/helm/values
# Release order: the first install of a service with a migration waits for its Job.
K8S_RELEASES := product-service inventory-service order-service inventory-consumer order-relay order-consumer notification-service notification-consumer
COMPOSE_APPS := product-service inventory-service inventory-consumer order-service order-relay order-consumer notification-service notification-consumer ui gateway
TRAEFIK_VERSION := 41.6.1
METRICS_SERVER_VERSION := 3.14.0

# Static checks only: helm lint and a render of every release; kubeconform when installed.
k8s-lint:
	@for env in local dev; do \
		for f in $(HV)/values-*-$$env.yaml; do \
			r=$$(basename $$f -$$env.yaml); r=$${r#values-}; [ "$$r" = common ] && continue; \
			extra=""; case $$r in ui|backing|ingress|ingress-public|secrets) ;; *) extra="-f $(HV)/values-common-$$env.yaml";; esac; \
			helm lint $(CHART) $$extra -f $$f --set image.tag=dev-lint >/dev/null || { echo "helm lint failed: $$env $$r"; exit 1; }; \
			helm template $$r $(CHART) $$extra -f $$f --set image.tag=dev-lint > /tmp/k8s-lint-$$env-$$r.yaml || exit 1; \
			if command -v kubeconform >/dev/null; then kubeconform -strict -summary -ignore-missing-schemas /tmp/k8s-lint-$$env-$$r.yaml || exit 1; fi; \
		done; \
	done
	@helm template d $(CHART) -f $(HV)/values-ui-dev.yaml --set image.repository=r/ui --set image.digest=sha256:abc | grep -q 'image: "r/ui@sha256:abc"' || { echo "image.digest is not rendered as repository@digest"; exit 1; }
	@helm lint deploy/helm/secret-store --set region=us-east-1 >/dev/null || { echo "helm lint failed: secret-store"; exit 1; }
	@command -v kubeconform >/dev/null || echo "kubeconform not installed: rendered manifests were not schema-checked"

# Images the cluster uses are the ones the local Docker engine builds: no registry, no push.
k8s-build:
	@for s in $(SERVICES); do \
		docker buildx build --load -f services/$$s/Dockerfile -t retail/$$s:$(IMAGE_TAG) . || exit 1; \
	done
	docker buildx build --load --build-arg VITE_DEMO_TOOLS=true -t retail/ui:$(IMAGE_TAG) ui

# Proves every image also builds for amd64 (the Graviton/arm64 build above is native). Nothing
# is loaded or pushed; this is slow because amd64 runs under emulation.
k8s-build-multiarch:
	@docker buildx inspect retail-multiarch >/dev/null 2>&1 || docker buildx create --name retail-multiarch --driver docker-container >/dev/null
	@for s in $(SERVICES); do \
		docker buildx build --builder retail-multiarch --platform linux/arm64,linux/amd64 -f services/$$s/Dockerfile . || exit 1; \
	done
	docker buildx build --builder retail-multiarch --platform linux/arm64,linux/amd64 ui

# Database passwords from .env become Secrets (the same names External Secrets creates on EKS).
# They go in through a pipe and a file descriptor: never on a command line or in a values file.
k8s-secrets: .env
	@kubectl --context $(K8S_CONTEXT) create namespace retail --dry-run=client -o yaml | kubectl --context $(K8S_CONTEXT) apply -f - >/dev/null
	@set -a; . ./.env; set +a; \
	for pair in product-app-db:PRODUCT_APP_PASSWORD product-owner-db:PRODUCT_OWNER_PASSWORD order-app-db:ORDER_APP_PASSWORD order-owner-db:ORDER_OWNER_PASSWORD; do \
		name=$${pair%%:*}; var=$${pair##*:}; \
		$(KUBECTL) create secret generic $$name --from-file=DB_PASSWORD=<(printf %s "$${!var}") --dry-run=client -o yaml | $(KUBECTL) apply -f - >/dev/null || exit 1; \
		echo "secret/$$name applied"; \
	done

# Traefik (ingress) and, if `kubectl top` does not work yet, metrics-server (the HPAs need it).
k8s-ingress:
	helm repo add traefik https://traefik.github.io/charts --force-update >/dev/null
	helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ --force-update >/dev/null
	helm --kube-context $(K8S_CONTEXT) upgrade --install traefik traefik/traefik --version $(TRAEFIK_VERSION) \
		-n traefik --create-namespace -f deploy/helm/third-party/traefik-local.yaml --rollback-on-failure --wait --timeout 3m
	@kubectl --context $(K8S_CONTEXT) top nodes >/dev/null 2>&1 || helm --kube-context $(K8S_CONTEXT) upgrade --install metrics-server \
		metrics-server/metrics-server --version $(METRICS_SERVER_VERSION) -n kube-system --set 'args={--kubelet-insecure-tls}' --rollback-on-failure --wait --timeout 3m

# Stops the Compose copies of the processes (two consumers of one queue, two relays of one outbox
# would be wrong), keeps the stores up, then installs every release with --rollback-on-failure: a release
# that does not become ready is rolled back and the target fails.
k8s-deploy: k8s-build k8s-secrets
	$(COMPOSE_NOAUTH) stop $(COMPOSE_APPS)
	$(COMPOSE) up -d --wait postgres valkey localstack
	$(HELM) upgrade --install --rollback-on-failure --wait --timeout 3m backing $(CHART) -f $(HV)/values-backing-local.yaml
	@for r in $(K8S_RELEASES); do \
		echo "== $$r"; \
		$(HELM) upgrade --install --rollback-on-failure --wait --timeout 3m $$r $(CHART) \
			-f $(HV)/values-common-local.yaml -f $(HV)/values-$$r-local.yaml --set image.tag=$(IMAGE_TAG) || exit 1; \
	done
	$(HELM) upgrade --install --rollback-on-failure --wait --timeout 3m ui $(CHART) -f $(HV)/values-ui-local.yaml --set image.tag=$(IMAGE_TAG)
	$(HELM) upgrade --install --rollback-on-failure --wait --timeout 3m gateway $(CHART) -f $(HV)/values-ingress-local.yaml
	$(KUBECTL) get pods
	@echo "Open http://retail.k8s.orb.local/  (make seed if LocalStack was restarted; make k8s-e2e to verify)"

# The same acceptance steps and browser journeys as Compose, through the Traefik ingress. The
# e2e suites stop and start processes through scripts/k8s_compose.py, which scales Deployments.
# They reach the ingress by `kubectl port-forward` rather than retail.k8s.orb.local: OrbStack's
# proxy for that name loses responses on reused keep-alive connections (Traefik logs a 200 the
# client never sees), and Chromium resolves *.local names through mDNS, which hangs. The four
# APIs are also forwarded, only because step 9 checks /health/ready on each.
K8S_E2E_ENV = E2E_K8S=1 E2E_GATEWAY_URL=http://localhost:18081 E2E_BASE_URL=http://localhost:18081 \
	K8S_COMPOSE_REAL="$(COMPOSE)" E2E_COMPOSE="python3 $(CURDIR)/scripts/k8s_compose.py"

k8s-e2e: sync ui/node_modules
	@pids=""; trap 'kill $$pids 2>/dev/null' EXIT; \
	kubectl --context $(K8S_CONTEXT) -n traefik port-forward svc/traefik 18081:80 >/dev/null 2>&1 & pids="$$!"; \
	for pair in product-service:8001 inventory-service:8002 order-service:8003 notification-service:8004; do \
		$(KUBECTL) port-forward svc/$${pair%%:*} $${pair##*:}:$${pair##*:} >/dev/null 2>&1 & pids="$$pids $$!"; \
	done; sleep 3; \
	$(K8S_E2E_ENV) PYTHONPATH=tests/e2e $(RUN) pytest tests/e2e/test_acceptance.py -q || exit 1; \
	cd ui && $(K8S_E2E_ENV) npm run e2e

# Deleting a pod of any workload while orders flow must lose none (needs the cluster; see the test).
k8s-resilience: sync
	@pids=""; trap 'kill $$pids 2>/dev/null' EXIT; \
	kubectl --context $(K8S_CONTEXT) -n traefik port-forward svc/traefik 18081:80 >/dev/null 2>&1 & pids="$$!"; sleep 3; \
	$(K8S_E2E_ENV) PYTHONPATH=tests/e2e $(RUN) pytest tests/e2e/test_k8s_resilience.py -q -s

# make k8s-rollback r=order-service [rev=3]   (no rev: the previous revision)
k8s-rollback:
	@test -n "$(r)" || { echo "usage: make k8s-rollback r=<release> [rev=<n>]"; exit 2; }
	$(HELM) rollback $(r) $(rev) --wait --timeout 3m
	$(HELM) history $(r) --max 5

k8s-down:
	-@for r in $$($(HELM) list -q); do $(HELM) uninstall $$r --wait; done
	-$(KUBECTL) delete secret product-app-db product-owner-db order-app-db order-owner-db
	@echo "Releases removed. Traefik stays. make up starts the Compose copies of the processes again."

# --- OpenAPI snapshots and the React UI (DESIGN.md section 15.7). Node is a prerequisite. ---------
# Specs are generated from each app's code (no connection is made), so a snapshot cannot drift
# from the service by hand-editing. `ui-types-check` fails when the generated types are stale.
openapi: sync
	@for s in $(SERVICES); do \
		PYTHONPATH=services/$$s $(RUN) python scripts/export_openapi.py $$s docs/openapi || exit 1; \
	done

openapi-check: sync
	@for s in $(SERVICES); do \
		PYTHONPATH=services/$$s $(RUN) python scripts/export_openapi.py $$s docs/openapi --check || exit 1; \
	done

ui-install:
	cd ui && npm ci

ui/node_modules: ui/package-lock.json
	cd ui && npm ci
	@touch ui/node_modules

ui-dev: ui/node_modules
	cd ui && VITE_DEMO_TOOLS=true npm run dev

ui-types: ui/node_modules
	cd ui && npm run types

ui-types-check: ui/node_modules
	cd ui && npm run types:check

ui-lint: ui/node_modules
	cd ui && npm run lint

ui-typecheck: ui/node_modules
	cd ui && npm run typecheck

ui-test: ui/node_modules
	cd ui && npm test

ui-build: ui/node_modules
	cd ui && npm run build

# Browser journeys against the running stack (`make up seed` first).
ui-e2e: ui/node_modules
	cd ui && E2E_COMPOSE="docker compose --env-file $(CURDIR)/.env -f $(CURDIR)/local/docker-compose.yml" npm run e2e

# --wait blocks until postgres, valkey and localstack (whose healthcheck waits for the bootstrap
# script) are healthy, and fails if a container exits, e.g. LocalStack without a token.
up: .env
	$(COMPOSE) up -d --build --wait
	$(COMPOSE) ps

# --profile observability: without it Compose would leave Prometheus and Grafana running.
down: .env
	$(COMPOSE_NOAUTH) --profile observability down

reset: .env
	$(COMPOSE_NOAUTH) --profile observability down -v

# Prometheus on :9090 and the RED / queue / outbox dashboard in Grafana on :3000.
obs-up: .env
	$(COMPOSE) --profile observability up -d --wait prometheus grafana

obs-down: .env
	$(COMPOSE_NOAUTH) --profile observability rm -sf prometheus grafana

logs: .env
	$(COMPOSE_NOAUTH) logs -f $(s)

# Catalog into product_db and stock into DynamoDB. Idempotent; needs `make up` first.
seed: .env
	$(COMPOSE) --profile tools run --rm --build seed
