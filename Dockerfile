# syntax=docker/dockerfile:1

# Build stage: resolve dependencies from uv.lock into a self-contained venv.
# uv arrives as a pinned binary rather than via a combined uv+python tag, so
# the uv version and the Python version are pinned independently.
FROM python:3.14-slim-bookworm AS builder

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
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# pg_dump/pg_restore for the nightly backup task. The client major must match
# the server (pgvector/pgvector:pg18); Debian bookworm ships 15, so the client
# comes from PGDG rather than the distro. A newer client can read an older
# server, but not the reverse -- pinning to 18 is what keeps a future server
# upgrade from silently breaking backups.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged: nothing in this image needs to write outside its own venv.
RUN groupadd --system --gid 1001 hope \
    && useradd --system --uid 1001 --gid hope --create-home hope

WORKDIR /app

# celery beat writes its last-run state here. A named volume mounted on a path
# the image does not create would be owned by root, and the unprivileged user
# could not write the schedule file.
RUN install -d -o hope -g hope /var/lib/celery

COPY --from=builder --chown=hope:hope /app /app

USER hope

EXPOSE 8000

# Mirrors the compose healthcheck so the image is self-describing when run
# outside compose.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"

CMD ["uvicorn", "hope_job_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
