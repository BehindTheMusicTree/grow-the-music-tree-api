#!/bin/bash
set -e

log () {
    echo "[start-server] $1"
}

log "Starting the api container..."

DB_HOST_PORT=$(python3 -c "
from urllib.parse import urlparse
import os
u = urlparse(os.environ['DATABASE_URL'])
print(u.hostname or '', u.port or 5432)
")
DB_HOST=$(echo "$DB_HOST_PORT" | cut -d' ' -f1)
DB_PORT=$(echo "$DB_HOST_PORT" | cut -d' ' -f2)

log "Waiting for the database..."
bash "$(dirname "$0")/wait-for-postgres-db.sh" "$DB_HOST" "$DB_PORT" 20 2

log "Running Django system checks..."
python3 manage.py check

log "Applying migrations..."
python3 manage.py migrate

log "Starting Gunicorn..."
exec gunicorn grow.wsgi:application \
    --bind "0.0.0.0:${APP_PORT:-8000}" \
    --access-logfile=- \
    --error-logfile=- \
    --log-level=info
