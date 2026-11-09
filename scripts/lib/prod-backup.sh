#!/usr/bin/env bash
# Shared access to the latest gtmt-api-db prod backup in R2 (Coolify daily pg_dump). Sourced by scripts that restore it.

# Writes the latest backup to the given file.
gtmt_fetch_latest_dump() {
  local dump_file=$1
  : "${RCLONE_CONFIG:?RCLONE_CONFIG must point to an rclone config with an [r2] remote}"
  : "${R2_BACKUP_BUCKET_NAME:?R2_BACKUP_BUCKET_NAME must be set}"
  command -v rclone >/dev/null || { echo "rclone is required (brew install rclone)" >&2; return 1; }

  # Coolify's upload prefix; listing the whole bucket also walks the TMD asset snapshots and takes minutes.
  local prefix="data/coolify/backups/databases"
  local latest_object
  latest_object="$(rclone lsjson "r2:${R2_BACKUP_BUCKET_NAME}/${prefix}" --recursive --files-only \
    | python3 -c "
import json, sys
entries = [e for e in json.load(sys.stdin) if 'gtmt-api-db' in e['Path']]
entries.sort(key=lambda e: e['ModTime'], reverse=True)
print('${prefix}/' + entries[0]['Path'] if entries else '')
")"
  [ -n "$latest_object" ] || { echo "No gtmt-api-db backup found in ${R2_BACKUP_BUCKET_NAME}" >&2; return 1; }

  echo "Fetching ${latest_object}"
  rclone copyto "r2:${R2_BACKUP_BUCKET_NAME}/${latest_object}" "$dump_file"
  # shellcheck disable=SC2034 # read by the caller
  GTMT_LATEST_DUMP_OBJECT=$latest_object
}

# Usage: gtmt_validate_archive <dump-file> <pg_restore command...>; the command must read the archive from stdin.
gtmt_validate_archive() {
  local dump_file=$1
  shift
  # Read the whole dump before anything is wiped, so a truncated or non-archive file fails with the target intact.
  "$@" -f /dev/null <"$dump_file"
  # Reject legacy archives: their generated columns cannot be restored normally.
  local function_sql
  function_sql="$("$@" -f - --schema-only --function='grow_search_norm(text)' <"$dump_file")"
  if [[ "$function_sql" != *"public.unaccent("* || "$function_sql" != *"'public.unaccent'"* ]]; then
    echo "Archive does not contain the qualified search function; see docs/operations/backup-recovery.md" >&2
    return 1
  fi
}
