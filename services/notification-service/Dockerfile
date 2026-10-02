# syntax=docker/dockerfile:1
# Build context is the repo root so libs/common is included:
#   docker build -f services/notification-service/Dockerfile .

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY libs/common libs/common
COPY services/product-service/pyproject.toml services/product-service/pyproject.toml
COPY services/inventory-service/pyproject.toml services/inventory-service/pyproject.toml
COPY services/order-service/pyproject.toml services/order-service/pyproject.toml
COPY services/notification-service/pyproject.toml services/notification-service/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package notification-service

FROM python:3.13-slim
# The base image lags its own security fixes: apply them at build time. pip and setuptools are
# dropped because the app runs from the copied /opt/venv and never uses the base image's own.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall -y pip setuptools wheel

RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 services/notification-service/app /srv/app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/srv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
WORKDIR /srv
EXPOSE 8004
ENTRYPOINT ["python", "-m", "app"]
CMD ["api"]
