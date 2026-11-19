#!/usr/bin/env bash
# Runner capacity probe for the catalogue benchmark (#511 step 0, v2). Builds a synthetic prod-scale catalogue, dumps
# it, drops the source cluster, then restores it ONCE the way restore_execution.py does (pre-data, single-transaction
# data-only pg_restore, post-data, ANALYZE) into a cluster limited like the harness's PostgreSQL container (4 GB,
# 4 CPUs, default config). The second side is a reflink copy of that data dir (the work directory must be an XFS
# volume mounted with reflink=1), then diverged with the projection rebuilds, which is prepare.py's worst case.
# Measures the restored size, disk peak, pgsql_tmp peak, the real disk cost of the copy and the durations.
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

samples="$(dirname "$summary")/samples.tsv"
: >"$samples"
margin_mb=10240
completed=0

report() { echo "$*" | tee -a "$summary"; }
used_mb() { df --output=used -B1M "$work" | tail -1 | tr -d ' '; }
tmp_mb() {
  sudo find "$work" -path '*/base/pgsql_tmp/*' -type f -printf '%s\n' 2>/dev/null |
    awk '{ s += $1 } END { printf "%d", s / 1048576 }'
}
sample_loop() {
  while :; do
    printf '%s\t%s\t%s\n' "$(date +%s)" "$(used_mb)" "$(tmp_mb)" >>"$samples"
    sleep 10
  done
}
max_col() { awk -F'\t' -v since="${2:-0}" -v c="$1" '$1 >= since && $c + 0 > m { m = $c + 0 } END { print m + 0 }' "$samples"; }
gb() { awk -v m="$1" 'BEGIN { printf "%.1f GB", m / 1024 }'; }

timed_total=0
timed() {
  local label=$1 start=$SECONDS since
  since=$(date +%s)
  shift
  "$@"
  local took=$((SECONDS - start))
  timed_total=$((timed_total + took))
  printf '%s\t%s\t%s\n' "$(date +%s)" "$(used_mb)" "$(tmp_mb)" >>"$samples"
  report "| $label | ${took} s | $(gb "$(used_mb)") | $(gb "$(max_col 2 "$since")") |"
}
as_root() { docker run --rm -v "$work:/w" --entrypoint "$1" "$image" "${@:2}"; }

finish() {
  kill "${sampler:-0}" 2>/dev/null || true
  report ""
  report "## Disk"
  report ""
  report '```'
  df -h "$work" | tee -a "$summary"
  sudo du -sh "$work"/* 2>/dev/null | tee -a "$summary"
  report '```'
  local size peak tmp
  size=$(df --output=size -B1M "$work" | tail -1 | tr -d ' ')
  peak=$(max_col 2)
  tmp=$(max_col 3)
  report ""
  report "- volume size: $(gb "$size"), peak used: $(gb "$peak"), margin: $(gb $((size - peak)))"
  report "- peak pgsql_tmp: $(gb "$tmp")"
  report "- timed steps total: ${timed_total} s"
  if [[ $completed == 1 && $((size - peak)) -ge $margin_mb ]]; then
    report "- **verdict: fits** (margin of at least $(gb "$margin_mb"))"
  else
    report "- **verdict: does not fit, or the probe did not complete** (completed=$completed)"
  fi
}
trap finish EXIT
sample_loop </dev/null &
sampler=$!

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
report "| Step | Duration | Used after | Peak during |"
report "| --- | --- | --- | --- |"
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
report "| archive size | $(du -h "$work/archive/backup.dump" | cut -f1) | | |"

# The source side is no longer needed: dropping it is what lets one restored side plus a copy fit on the volume.
docker rm -f -v probe-source >/dev/null
as_root rm -rf /w/source
report "| source cluster removed | | $(gb "$(used_mb)") | |"

run_pg() {
  docker run -d --name "$1" --memory 4g --memory-swap 4g --cpus 4 -e POSTGRES_HOST_AUTH_METHOD=trust \
    -v "$work/$2:/var/lib/postgresql/data" ${3:+-p "$3:5432"} "${@:4}" "$image" >/dev/null
}
stop_pg() {
  docker stop --time 60 "$1" >/dev/null
  [[ $(docker inspect -f '{{.State.ExitCode}}' "$1") == 0 ]] || { echo "$1 did not stop cleanly" >&2; return 1; }
}
side() { docker exec -i "$1" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d btmt_grow_perf "${@:2}"; }

run_pg probe-restored restored "" -v "$work/archive:/restore:ro"
wait_ready probe-restored
dst -c "CREATE DATABASE btmt_grow_perf TEMPLATE template0"
restore_start=$SECONDS
timed "restore pre-data" dst -d btmt_grow_perf <"$work/pre.sql"
timed "restore data (single transaction)" docker exec probe-restored pg_restore -U postgres --dbname=btmt_grow_perf \
  --exit-on-error --single-transaction --no-owner --no-privileges --data-only /restore/backup.dump
rm -f "$work/archive/backup.dump"
timed "restore post-data (default config)" dst -d btmt_grow_perf <"$work/post.sql"
timed "restore ANALYZE" dst -d btmt_grow_perf -c ANALYZE
report "| **restore total, one side** | **$((SECONDS - restore_start)) s** | $(gb "$(used_mb)") | |"

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
report ""
report "| Step | Duration | Used after | Peak during |"
report "| --- | --- | --- | --- |"

stop_pg probe-restored
before_copy=$(used_mb)
timed "reflink copy of the restored data dir" as_root cp -a --reflink=always /w/restored /w/side-b
report "| copy disk cost | | $(gb $(($(used_mb) - before_copy))) | |"

# prepare.py rewrites the projections on each side: this is the real cost of keeping the two sides apart.
before_diverge=$(used_mb)
run_pg probe-side-b side-b 5433
wait_ready probe-side-b
export DATABASE_URL=postgres://postgres@localhost:5433/btmt_grow_perf
timed "side B rebuild_song_search" uv run --no-sync manage.py rebuild_song_search
timed "side B rebuild_artist_song" uv run --no-sync manage.py rebuild_artist_song
timed "side B ANALYZE" side probe-side-b -c ANALYZE
report "| divergence disk cost | | $(gb $(($(used_mb) - before_diverge))) | |"

# Both data dirs must coexist and start.
docker start probe-restored >/dev/null
wait_ready probe-restored
report "- side A grow_song rows: $(side probe-restored -At -c 'SELECT count(*) FROM grow_song')"
report "- side B grow_song rows: $(side probe-side-b -At -c 'SELECT count(*) FROM grow_song')"
stop_pg probe-restored
stop_pg probe-side-b
completed=1
