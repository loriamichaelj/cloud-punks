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

.PHONY: help lock sync fmt lint test itest e2e up down reset logs seed openapi ui-install ui-dev ui-types ui-lint ui-typecheck ui-test ui-build ui-e2e ui-types-check openapi-check

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
	@$(MAKE) --no-print-directory openapi-check ui-types-check ui-lint ui-typecheck ui-build

test: sync
	@echo "pytest libs/common (coverage gate: 80%)"
	@$(RUN) pytest libs/common/tests -q --cov=retail_common --cov-report=term-missing:skip-covered --cov-fail-under=80
	@for s in $(SERVICES); do \
		echo "pytest $$s"; \
		PYTHONPATH=services/$$s $(RUN) pytest services/$$s/tests/unit -q || exit 1; \
	done
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

down: .env
	$(COMPOSE_NOAUTH) down

reset: .env
	$(COMPOSE_NOAUTH) down -v

logs: .env
	$(COMPOSE_NOAUTH) logs -f $(s)

# Catalog into product_db and stock into DynamoDB. Idempotent; needs `make up` first.
seed: .env
	$(COMPOSE) --profile tools run --rm --build seed
