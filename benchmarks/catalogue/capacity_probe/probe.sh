#!/usr/bin/env bash
# Runner capacity probe for the catalogue benchmark (#511 step 0). Builds a synthetic prod-scale catalogue, dumps it,
# then restores it the way restore_execution.py does (pre-data, single-transaction data-only pg_restore, post-data,
# ANALYZE) into a second cluster limited like the harness's PostgreSQL container (4 GB, 4 CPUs, default config).
# The source cluster stays on disk during the restore, so peak usage is two sides plus the archive, as in a real run.
# Usage: probe.sh <work-dir> <summary-file>. Needs Docker and `uv sync` done; SONGS/ARTISTS/ALBUMS override the scale.
set -euo pipefail

work=$1
summary=$2
songs=${SONGS:-31300000}
artists=${ARTISTS:-1950000}
albums=${ALBUMS:-4340000}
here=$(cd "$(dirname "$0")" && pwd)
image=postgres:16
mkdir -p "$work"/{source,restored,archive}

report() { echo "$*" | tee -a "$summary"; }
timed() {
  local label=$1 start=$SECONDS
  shift
  "$@"
  report "| $label | $((SECONDS - start)) s |"
}
disk() { report ""; report '```'; df -h "$work" | tee -a "$summary"; du -sh "$work"/* 2>/dev/null | tee -a "$summary"; report '```'; }
trap disk EXIT

wait_ready() { until docker exec "$1" pg_isready -q -U postgres; do sleep 1; done; }
src() { docker exec -i probe-source psql -X -q -o /dev/null -v ON_ERROR_STOP=1 -U postgres "$@"; }
dst() { docker exec -i probe-restored psql -X -q -v ON_ERROR_STOP=1 -U postgres "$@"; }

# Generation is not what is measured, so the source cluster gets whatever helps it load fast.
docker run -d --name probe-source -p 5432:5432 -e POSTGRES_HOST_AUTH_METHOD=trust \
  -v "$work/source:/var/lib/postgresql/data" "$image" \
  -c shared_buffers=3GB -c maintenance_work_mem=2GB -c max_wal_size=16GB -c wal_level=minimal \
  -c max_wal_senders=0 -c synchronous_commit=off -c checkpoint_timeout=30min >/dev/null
wait_ready probe-source
docker run -d --name probe-redis -p 6379:6379 redis:7-alpine >/dev/null
src -c "CREATE DATABASE schema_src" -c "CREATE DATABASE catalogue"

export DATABASE_URL=postgres://postgres@localhost:5432/schema_src
export SECRET_KEY=probe PIPELINE_API_KEY=probe CURATION_API_KEY=probe GOOGLE_OAUTH_CLIENT_ID=probe \
  ADMIN_GOOGLE_SUB=probe YOUTUBE_API_KEY=probe REDIS_URL=redis://localhost:6379/0
uv run --no-sync manage.py migrate --no-input >/dev/null

report "## Synthetic catalogue: $songs songs, $artists artists, $albums albums"
report ""
report "| Step | Duration |"
report "| --- | --- |"
docker exec probe-source pg_dump -U postgres --schema-only --section=pre-data schema_src | src -d catalogue
timed "generate rows (no indexes)" src -d catalogue -v songs="$songs" -v artists="$artists" -v albums="$albums" \
  <"$here/generate.sql"
docker exec probe-source pg_dump -U postgres --schema-only --section=post-data schema_src >"$work/post.sql"
timed "source post-data (tuned)" src -d catalogue <"$work/post.sql"

export DATABASE_URL=postgres://postgres@localhost:5432/catalogue
timed "rebuild_song_search" uv run --no-sync manage.py rebuild_song_search
timed "rebuild_artist_song" uv run --no-sync manage.py rebuild_artist_song
timed "source ANALYZE" src -d catalogue -c ANALYZE

# The projections swap tables in, so the restore uses the catalogue's own schema, not schema_src's.
docker exec probe-source pg_dump -U postgres --schema-only --section=pre-data catalogue >"$work/pre.sql"
docker exec probe-source pg_dump -U postgres --schema-only --section=post-data catalogue >"$work/post.sql"
timed "pg_dump -Fc" sh -c "docker exec probe-source pg_dump -U postgres -Fc --data-only catalogue >'$work/archive/backup.dump'"
report "| archive size | $(du -h "$work/archive/backup.dump" | cut -f1) |"

docker run -d --name probe-restored --memory 4g --memory-swap 4g --cpus 4 -e POSTGRES_HOST_AUTH_METHOD=trust \
  -v "$work/restored:/var/lib/postgresql/data" -v "$work/archive:/restore:ro" "$image" >/dev/null
wait_ready probe-restored
dst -c "CREATE DATABASE btmt_grow_perf TEMPLATE template0"
restore_start=$SECONDS
timed "restore pre-data" dst -d btmt_grow_perf <"$work/pre.sql"
timed "restore data (single transaction)" docker exec probe-restored pg_restore -U postgres --dbname=btmt_grow_perf \
  --exit-on-error --single-transaction --no-owner --no-privileges --data-only /restore/backup.dump
timed "restore post-data (default config)" dst -d btmt_grow_perf <"$work/post.sql"
timed "restore ANALYZE" dst -d btmt_grow_perf -c ANALYZE
report "| **restore total, one side** | **$((SECONDS - restore_start)) s** |"

report ""
report "### Restored sizes"
report ""
report '```'
dst -d btmt_grow_perf -A -F ' | ' -c "
  SELECT c.relname, c.reltuples::bigint AS rows, pg_size_pretty(pg_relation_size(c.oid)) AS heap,
         pg_size_pretty(pg_indexes_size(c.oid)) AS idx, pg_size_pretty(pg_total_relation_size(c.oid)) AS total
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE c.relkind = 'r' AND n.nspname = 'public' AND pg_total_relation_size(c.oid) > 10 * 1024 * 1024
  UNION ALL SELECT '__database', NULL, NULL, NULL, pg_size_pretty(pg_database_size(current_database()))
  ORDER BY 1" | tee -a "$summary"
report '```'
