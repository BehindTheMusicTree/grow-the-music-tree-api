# syntax=docker/dockerfile:1
FROM python:3.14-bookworm

ARG APP_VERSION
ARG APP_NAME=gtmt-api

RUN for var in APP_VERSION; do \
    eval "value=\$$var"; \
    if [ -z "$value" ]; then \
        echo "ERROR: The $var argument is not provided" >&2; \
        exit 1; \
    fi; \
done

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROJECT_DIR=/home/app/ \
    APP_VERSION=$APP_VERSION \
    APP_NAME=$APP_NAME \
    PATH="/home/app/.venv/bin:$PATH"

RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . $PROJECT_DIR

WORKDIR $PROJECT_DIR

RUN uv sync --frozen --no-dev

RUN chmod +x scripts/entrypoint.sh scripts/start-server.sh scripts/wait-for-postgres-db.sh

HEALTHCHECK --interval=10s --timeout=6s --retries=5 --start-period=60s \
    CMD python3 -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"APP_PORT\", \"8001\")}/health/', timeout=5)"

ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
CMD ["bash", "scripts/start-server.sh"]
