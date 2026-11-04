# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.13.5

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src

COPY --from=uv /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRENDSMAPP_ENVIRONMENT=production

WORKDIR /app

RUN groupadd --system --gid 10001 trendsmapp \
    && useradd --system --uid 10001 --gid trendsmapp --create-home trendsmapp \
    && mkdir -p /app/var/objects \
    && chown -R trendsmapp:trendsmapp /app

COPY --from=builder --chown=trendsmapp:trendsmapp /opt/venv /opt/venv
COPY --from=builder --chown=trendsmapp:trendsmapp /src/migrations /app/migrations
COPY --from=builder --chown=trendsmapp:trendsmapp /src/alembic.ini /app/alembic.ini

USER trendsmapp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4)"]

CMD ["uvicorn", "trendsmapp.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
