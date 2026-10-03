#!/bin/bash
# Replace the local docker compose DB with the latest prod backup from R2 (Coolify daily pg_dump).
# Safe to share: grow's DB only holds the public canonical dataset (no user data).
# Usage: RCLONE_CONFIG=<config with an [r2] remote> R2_BACKUP_BUCKET_NAME=<bucket> ./scripts/restore-prod-db.sh
set -euo pipefail

: "${RCLONE_CONFIG:?RCLONE_CONFIG must point to an rclone config with an [r2] remote}"
: "${R2_BACKUP_BUCKET_NAME:?R2_BACKUP_BUCKET_NAME must be set}"
command -v rclone >/dev/null || { echo "rclone is required (brew install rclone)" >&2; exit 1; }

cd "$(dirname "$0")/.."

# Coolify's upload prefix; listing the whole bucket also walks the TMD asset snapshots and takes minutes.
prefix="data/coolify/backups/databases"
latest_object="$(rclone lsjson "r2:${R2_BACKUP_BUCKET_NAME}/${prefix}" --recursive --files-only \
  | python3 -c "
import json, sys
entries = [e for e in json.load(sys.stdin) if 'gtmt-api-db' in e['Path']]
entries.sort(key=lambda e: e['ModTime'], reverse=True)
print('${prefix}/' + entries[0]['Path'] if entries else '')
")"
[ -n "$latest_object" ] || { echo "No gtmt-api-db backup found in ${R2_BACKUP_BUCKET_NAME}" >&2; exit 1; }

dump_file="$(mktemp -t gtmt-prod-dump.XXXXXX)"
trap 'rm -f "$dump_file"' EXIT
echo "Fetching ${latest_object}"
rclone copyto "r2:${R2_BACKUP_BUCKET_NAME}/${latest_object}" "$dump_file"

docker compose stop api worker
docker compose up -d --wait db
# Read the whole dump before wiping anything, so a truncated or non-archive file fails with the local DB intact.
docker compose exec -T db pg_restore -f /dev/null <"$dump_file"
# pg_restore --clean only drops objects in the dump: tables from local migrations prod hasn't run yet would survive
# and make migrate fail with "already exists", so start from an empty schema.
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <"$dump_file"
# start-server.sh applies this branch's migrations on top of prod's schema.
docker compose up -d --wait api worker
echo "Restored ${latest_object}"
