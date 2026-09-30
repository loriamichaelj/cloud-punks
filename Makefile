SHELL := /bin/bash

SERVICES := product-service inventory-service order-service notification-service

# Compose must always read the repo-root .env; without --env-file it would read local/.env
# and ${VAR} interpolation would silently produce empty passwords (DESIGN.md section 10).
COMPOSE = docker compose --env-file .env -f local/docker-compose.yml

# Images are tagged dev-<git sha>, never :latest.
IMAGE_TAG ?= dev-$(shell git rev-parse --short HEAD 2>/dev/null || echo nogit)
export IMAGE_TAG

RUN = uv run --frozen --no-sync

.PHONY: help lock sync fmt lint test up down reset logs

help:
	@echo "Targets: lock sync fmt lint test up down reset logs s=<service>"

.env:
	cp .env.example .env
	@echo "Created .env from .env.example (git-ignored). Set LOCALSTACK_AUTH_TOKEN before M2."

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

test: sync
	@echo "pytest libs/common (coverage gate: 80%)"
	@$(RUN) pytest libs/common/tests -q --cov=retail_common --cov-report=term-missing:skip-covered --cov-fail-under=80
	@for s in $(SERVICES); do \
		echo "pytest $$s"; \
		PYTHONPATH=services/$$s $(RUN) pytest services/$$s/tests/unit -q || exit 1; \
	done

up: .env
	$(COMPOSE) up -d --build
	$(COMPOSE) ps

down: .env
	$(COMPOSE) down

reset: .env
	$(COMPOSE) down -v

logs: .env
	$(COMPOSE) logs -f $(s)
