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

ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
CMD ["bash", "scripts/start-server.sh"]
