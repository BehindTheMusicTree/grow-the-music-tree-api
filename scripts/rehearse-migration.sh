#!/usr/bin/env bash
# Rehearse pending migrations on a disposable copy of the prod backup, then destroy it. See docs/operations/migration-rehearsal.md.
#
# Usage: scripts/rehearse-migration.sh --image <api image> --pg-image <postgres image> --pg-conf <postgresql.conf>
#          (--dump <file> | --fetch-latest) [--target "<app> <migration>"] [--warm-sql <file>]
#          [--hold-lock "<table>:<LOCK MODE>" [--expect-failure]] [--verify "<command>"]
#          [--runs N] [--keep] [--pg-memory 8g] [--restore-jobs 2]
# --fetch-latest needs RCLONE_CONFIG and R2_BACKUP_BUCKET_NAME.
set -euo pipefail

usage() {
  sed -n '2,8p' "$0" >&2
  exit 2
}
die() {
  echo "rehearse-migration: $*" >&2
  exit 1
}

script_dir=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=scripts/lib/prod-backup.sh
source "$script_dir/lib/prod-backup.sh"

image="" pg_image="" pg_conf="" dump="" fetch_latest=0 target="" warm_sql="" hold_lock="" expect_failure=0
verify="" runs=1 keep=0 pg_memory=8g restore_jobs=2
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fetch-latest) fetch_latest=1; shift ;;
    --expect-failure) expect_failure=1; shift ;;
    --keep) keep=1; shift ;;
    --image | --pg-image | --pg-conf | --dump | --target | --warm-sql | --hold-lock | --verify | --runs | --pg-memory | --restore-jobs)
      [[ $# -ge 2 ]] || usage
      case "$1" in
        --image) image=$2 ;;
        --pg-image) pg_image=$2 ;;
        --pg-conf) pg_conf=$2 ;;
        --dump) dump=$2 ;;
        --target) target=$2 ;;
        --warm-sql) warm_sql=$2 ;;
        --hold-lock) hold_lock=$2 ;;
        --verify) verify=$2 ;;
        --runs) runs=$2 ;;
        --pg-memory) pg_memory=$2 ;;
        --restore-jobs) restore_jobs=$2 ;;
      esac
      shift 2
      ;;
    *) usage ;;
  esac
done

[[ -n $image && -n $pg_image && -n $pg_conf ]] || usage
if [[ $fetch_latest -eq 1 && -n $dump ]] || [[ $fetch_latest -eq 0 && -z $dump ]]; then
  die "pass exactly one of --dump and --fetch-latest"
fi
[[ $runs =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer"
[[ $restore_jobs =~ ^[1-9][0-9]*$ ]] || die "--restore-jobs must be a positive integer"
[[ -r $pg_conf ]] || die "cannot read $pg_conf"
[[ -z $warm_sql || -r $warm_sql ]] || die "cannot read $warm_sql"
[[ -z $dump || -r $dump ]] || die "cannot read $dump"
[[ $expect_failure -eq 0 || -n $hold_lock ]] || die "--expect-failure needs --hold-lock"
hold_table="" hold_mode=""
if [[ -n $hold_lock ]]; then
  hold_table=${hold_lock%%:*}
  hold_mode=${hold_lock#*:}
  [[ $hold_table =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ && $hold_mode =~ ^[A-Z]+( [A-Z]+)*$ ]] \
    || die "--hold-lock must look like grow_song:ACCESS SHARE"
fi

absolute_path() {
  echo "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
}
pg_conf=$(absolute_path "$pg_conf")
[[ -z $dump ]] || dump=$(absolute_path "$dump")

target_args=()
[[ -z $target ]] || read -r -a target_args <<<"$target"
verify_args=()
[[ -z $verify ]] || read -r -a verify_args <<<"$verify"

run_id="$(date -u +%Y%m%d%H%M%S)-$$"
prefix="rehearsal-$run_id"
pg_container="$prefix-pg"
network="$prefix-net"
volume="$prefix-vol"
source_db=rehearsal_source
pg_password=rehearsal
work_dir=$(mktemp -d)
holder_pid="" sampler_pid=""

release_lock() {
  [[ -n $holder_pid ]] || return 0
  pg_sql postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 'rehearsal-hold'" >/dev/null 2>&1 || true
  wait "$holder_pid" 2>/dev/null || true
  holder_pid=""
}

stop_sampler() {
  [[ -n $sampler_pid ]] || return 0
  kill "$sampler_pid" 2>/dev/null || true
  wait "$sampler_pid" 2>/dev/null || true
  sampler_pid=""
}

# shellcheck disable=SC2329 # invoked by the EXIT trap
cleanup() {
  local status=$?
  stop_sampler
  release_lock
  rm -rf "$work_dir"
  docker ps -aq --filter "label=rehearsal.oneshot=$run_id" | while read -r id; do
    docker rm -f "$id" >/dev/null 2>&1 || true
  done
  if [[ $keep -eq 1 ]]; then
    echo "Kept run $run_id. Destroy with: docker rm -f $pg_container && docker network rm $network && docker volume rm $volume"
  else
    docker rm -f "$pg_container" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

pg_sql() {
  local db=$1
  shift
  docker exec "$pg_container" psql -X -q -A -t -v ON_ERROR_STOP=1 -U postgres -d "$db" "$@"
}

ensure_image() {
  docker image inspect "$1" >/dev/null 2>&1 || docker pull "$1"
}

docker info >/dev/null || die "Docker is not reachable"
ensure_image "$image"
ensure_image "$pg_image"

if [[ $fetch_latest -eq 1 ]]; then
  dump="$work_dir/gtmt-prod.dump"
  gtmt_fetch_latest_dump "$dump"
fi

# A dump from a different major would measure a planner and storage that prod does not run.
dump_listing=$(docker run --rm -i --network none "$pg_image" pg_restore --list <"$dump") \
  || die "$pg_image cannot read this dump (older major than the server that made it, or not an archive)"
dump_major=$(sed -n 's/^;[[:space:]]*Dumped from database version: \([0-9][0-9]*\).*/\1/p' <<<"$dump_listing")
image_major=$(docker run --rm --network none "$pg_image" pg_restore --version | sed -n 's/^pg_restore (PostgreSQL) \([0-9][0-9]*\).*/\1/p')
[[ -n $dump_major && -n $image_major ]] || die "could not read the PostgreSQL major of the dump or of $pg_image"
[[ $dump_major == "$image_major" ]] || die "dump is from PostgreSQL $dump_major but $pg_image is $image_major"

gtmt_validate_archive "$dump" docker run --rm -i --network none "$pg_image" pg_restore

branch=$(git -C "$script_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
labels=(--label "rehearsal.run=$run_id" --label "rehearsal.branch=$branch" --label "rehearsal.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)")

docker volume create "${labels[@]}" "$volume" >/dev/null
# Measured on the volume: on Docker Desktop the host's filesystem is not the one that fills up.
free_kb=$(docker run --rm --network none -v "$volume:/data" "$pg_image" df -Pk /data | awk 'END { print $4 }')
dump_kb=$(($(wc -c <"$dump") / 1024))
required_kb=$((dump_kb * 10))
[[ $free_kb -ge $required_kb ]] || die "need ${required_kb} KiB free for this dump, the Docker volume has ${free_kb} KiB"

docker network create --internal "${labels[@]}" "$network" >/dev/null
docker run -d --name "$pg_container" --network "$network" "${labels[@]}" \
  --memory "$pg_memory" --memory-swap "$pg_memory" \
  -e POSTGRES_PASSWORD="$pg_password" \
  -v "$volume:/var/lib/postgresql/data" \
  -v "$pg_conf:/etc/rehearsal/postgresql.conf:ro" \
  -v "$dump:/rehearsal/dump.bin:ro" \
  "$pg_image" postgres -c config_file=/etc/rehearsal/postgresql.conf >/dev/null

# TCP only: the image's init server answers on the Unix socket and then restarts.
for _ in $(seq 1 120); do
  docker exec "$pg_container" pg_isready -q -h 127.0.0.1 -U postgres && break
  [[ $(docker inspect -f '{{.State.Running}}' "$pg_container") == true ]] || {
    docker logs --tail 20 "$pg_container" >&2
    die "Postgres exited during startup"
  }
  sleep 1
done
docker exec "$pg_container" pg_isready -q -h 127.0.0.1 -U postgres || die "Postgres never accepted connections"

echo "Restoring $(basename "$dump") into $source_db"
restore_started=$SECONDS
pg_sql postgres -c "CREATE DATABASE $source_db"
docker exec "$pg_container" pg_restore --exit-on-error --no-owner --no-privileges --jobs "$restore_jobs" \
  -U postgres -d "$source_db" /rehearsal/dump.bin
pg_sql "$source_db" -c "ANALYZE"
echo "Restored and analyzed in $((SECONDS - restore_started)) s"

django_run() {
  local db=$1 name=$2
  shift 2
  docker run --rm --name "$prefix-$name" --network "$network" --label "rehearsal.oneshot=$run_id" \
    -e DATABASE_URL="postgresql://postgres:$pg_password@$pg_container:5432/$db" \
    -e REDIS_URL=redis://127.0.0.1:6379/0 \
    -e SECRET_KEY=rehearsal \
    -e PIPELINE_API_KEY=rehearsal \
    -e CURATION_API_KEY=rehearsal \
    -e GOOGLE_OAUTH_CLIENT_ID=rehearsal \
    -e ADMIN_GOOGLE_SUB=rehearsal \
    -e YOUTUBE_API_KEY=rehearsal \
    "$image" "$@"
}

applied_migrations() {
  pg_sql "$1" -c "SELECT app || '.' || name FROM django_migrations" | LC_ALL=C sort
}

hold_lock_on() {
  local db=$1 waited
  docker exec -e PGAPPNAME=rehearsal-hold "$pg_container" \
    psql -X -q -v ON_ERROR_STOP=1 -U postgres -d "$db" \
    -c "BEGIN" -c "LOCK TABLE $hold_table IN $hold_mode MODE" -c "SELECT pg_sleep(86400)" >/dev/null 2>&1 &
  holder_pid=$!
  for waited in $(seq 1 30); do
    [[ $(pg_sql postgres -c "SELECT count(*) FROM pg_stat_activity WHERE application_name = 'rehearsal-hold' AND wait_event = 'PgSleep'") == 1 ]] && return 0
    [[ $waited -lt 30 ]] && sleep 1
  done
  die "could not take $hold_mode on $hold_table"
}

sample_blocked_locks() {
  local db=$1 file=$2 peak=0 current
  echo 0 >"$file"
  while :; do
    current=$(pg_sql postgres -c "SELECT count(*) FROM pg_locks WHERE NOT granted AND database = (SELECT oid FROM pg_database WHERE datname = '$db')" 2>/dev/null || echo 0)
    if [[ $current -gt $peak ]]; then
      peak=$current
      echo "$peak" >"$file"
    fi
    sleep 1
  done
}

overall=0
for run in $(seq 1 "$runs"); do
  db="rehearsal_run_$run"
  echo "=== Run $run/$runs on $db"
  pg_sql postgres -c "CREATE DATABASE $db TEMPLATE $source_db"
  cache=cold
  if [[ -n $warm_sql ]]; then
    docker exec -i "$pg_container" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d "$db" >/dev/null <"$warm_sql"
    cache=warm
  fi
  # After the clone: CREATE DATABASE writes the whole copy to WAL, which is not the migration's cost.
  pg_sql postgres -c "CHECKPOINT"

  applied_migrations "$db" >"$work_dir/before"
  start_lsn=$(pg_sql postgres -c "SELECT pg_current_wal_lsn()")
  temp_before=$(pg_sql postgres -c "SELECT temp_bytes FROM pg_stat_database WHERE datname = '$db'")

  [[ -z $hold_lock ]] || hold_lock_on "$db"
  sample_blocked_locks "$db" "$work_dir/peak" &
  sampler_pid=$!

  migrate_started=$SECONDS
  if django_run "$db" "migrate-$run" python3 manage.py migrate --no-input ${target_args[@]+"${target_args[@]}"}; then
    migrate_status=0
  else
    migrate_status=$?
  fi
  duration=$((SECONDS - migrate_started))

  stop_sampler
  release_lock

  applied_migrations "$db" >"$work_dir/after"
  wal_bytes=$(pg_sql postgres -c "SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '$start_lsn')::bigint")
  temp_after=$(pg_sql postgres -c "SELECT temp_bytes FROM pg_stat_database WHERE datname = '$db'")
  applied=$(LC_ALL=C comm -13 "$work_dir/before" "$work_dir/after" | paste -sd ' ' -)

  verify_result=skipped
  if [[ $expect_failure -eq 1 ]]; then
    if [[ $migrate_status -eq 0 ]]; then
      result="FAIL: migrate succeeded while the lock was held"
    elif ! cmp -s "$work_dir/before" "$work_dir/after"; then
      result="FAIL: migrate failed but django_migrations changed"
    else
      result="ok: migrate failed as expected and django_migrations is unchanged"
    fi
  elif [[ $migrate_status -ne 0 ]]; then
    result="FAIL: migrate exited $migrate_status"
  else
    result=ok
    if [[ -n $verify ]]; then
      if django_run "$db" "verify-$run" "${verify_args[@]}"; then
        verify_result=ok
      else
        verify_result="exit $?"
        result="FAIL: verify failed"
      fi
    fi
  fi
  [[ $result == ok* ]] || overall=1

  cat <<REPORT
--- Run $run report
result:          $result
cache:           $cache
migrate exit:    $migrate_status
duration:        $duration s
wal:             $wal_bytes bytes
temp files:      $((temp_after - temp_before)) bytes
peak blocked:    $(cat "$work_dir/peak") ungranted locks
verify:          $verify_result
applied:         ${applied:-none}
REPORT
done

exit "$overall"
