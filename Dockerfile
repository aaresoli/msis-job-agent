# syntax=docker/dockerfile:1

# Build stage: resolve dependencies from uv.lock into a self-contained venv.
# uv arrives as a pinned binary rather than via a combined uv+python tag, so
# the uv version and the Python version are pinned independently.
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve from the lockfile alone, so this layer stays cached
# until the lockfile itself changes -- application edits do not invalidate it.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# Runtime stage: the venv and the application, no build tooling, no uv.
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Unprivileged: nothing in this image needs to write outside its own venv.
RUN groupadd --system --gid 1001 hope \
    && useradd --system --uid 1001 --gid hope --create-home hope

WORKDIR /app

COPY --from=builder --chown=hope:hope /app /app

USER hope

EXPOSE 8000

# Mirrors the compose healthcheck so the image is self-describing when run
# outside compose.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"

CMD ["uvicorn", "hope_job_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
