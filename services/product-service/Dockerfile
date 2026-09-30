# syntax=docker/dockerfile:1
# Build context is the repo root so libs/common is included:
#   docker build -f services/product-service/Dockerfile .

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
    uv sync --frozen --no-dev --no-editable --package product-service

FROM python:3.13-slim
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 services/product-service/app /srv/app
# Dev-only seed job (`python -m app seed`), per DESIGN.md section 10.
COPY --chown=10001:10001 local/seed /srv/seed
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/srv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
WORKDIR /srv
EXPOSE 8001
ENTRYPOINT ["python", "-m", "app"]
CMD ["api"]
