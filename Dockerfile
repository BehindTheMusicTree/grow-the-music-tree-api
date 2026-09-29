# syntax=docker/dockerfile:1
FROM python:3.14-slim-bookworm AS base

ARG APP_NAME=gtmt-api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROJECT_DIR=/home/app/ \
    APP_NAME=$APP_NAME \
    PATH="/home/app/.venv/bin:$PATH"

RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR $PROJECT_DIR

# Also the local dev target (docker-compose.override.yml), which runs uv sync at startup.
FROM base AS builder

# uv clones the kits over git+https.
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . $PROJECT_DIR

RUN uv sync --frozen --no-dev

FROM base

# Same path as the builder: the venv's scripts hardcode it in their shebangs.
COPY --from=builder $PROJECT_DIR $PROJECT_DIR

RUN chmod +x scripts/entrypoint.sh scripts/start-server.sh scripts/wait-for-postgres-db.sh

# Last so a new commit doesn't invalidate the cached layers above. Not SOURCE_COMMIT: Coolify
# overrides that one at runtime (with "HEAD" for image-based apps).
ARG GIT_COMMIT
ENV GIT_COMMIT=$GIT_COMMIT

# The django-q2 worker reuses this image with qcluster as PID 1 and serves no HTTP; Coolify still
# waits on this HEALTHCHECK to accept its deploys, so pass while that process is alive.
HEALTHCHECK --interval=10s --timeout=6s --retries=5 --start-period=60s \
    CMD grep -q qcluster /proc/1/cmdline || python3 -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"APP_PORT\", \"8000\")}/health/', timeout=5)"

ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
CMD ["bash", "scripts/start-server.sh"]
