#!/bin/bash
# Replace the local docker compose DB with the latest prod backup from R2 (Coolify daily pg_dump).
# Safe to share: grow's DB only holds the public canonical dataset (no user data).
# Usage: RCLONE_CONFIG=<config with an [r2] remote> R2_BACKUP_BUCKET_NAME=<bucket> ./scripts/restore-prod-db.sh
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib/prod-backup.sh
source scripts/lib/prod-backup.sh

dump_file="$(mktemp -t gtmt-prod-dump.XXXXXX)"
trap 'rm -f "$dump_file"' EXIT
gtmt_fetch_latest_dump "$dump_file"
latest_object=$GTMT_LATEST_DUMP_OBJECT

docker compose up -d --wait db
gtmt_validate_archive "$dump_file" docker compose exec -T db pg_restore
docker compose stop api worker
# pg_restore --clean only drops objects in the dump: tables from local migrations prod hasn't run yet would survive
# and make migrate fail with "already exists", so start from an empty schema.
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
docker compose exec -T db sh -c 'pg_restore --exit-on-error --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <"$dump_file"
# start-server.sh applies this branch's migrations on top of prod's schema.
docker compose up -d --wait api worker
echo "Restored ${latest_object}"
