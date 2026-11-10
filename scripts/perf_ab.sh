#!/usr/bin/env bash
# Same-runner A/B perf gate: runs perf/ on the base and head checkouts in turn (base, head, base, head), each against
# its own seeded Postgres database, then judges the results with perf/compare.py. Round i of base and round i of head
# run back to back and are paired there, so drift shared by both cancels and a slowdown shows against the base instead
# of against a fixed threshold. Keep the strict alternation and the <side>-<round>.json names: the pairing relies on them.
#
# Usage: PERF_PG_URL=postgres://user:pass@host:port scripts/perf_ab.sh <base-dir|none> <head-dir> <out-dir>
# With `none` as base (pushes), only the head's SLOs are judged, still on the median pooled over two runs.
# Optional: PERF_ACCEPT_REGRESSIONS=1 (label perf-regression-accepted), PERF_SUMMARY=<markdown file to append to>.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  sed -n '2,9p' "$0" >&2
  exit 2
fi
: "${PERF_PG_URL:?PERF_PG_URL must name the Postgres server, without a database}"
base_dir=none
if [[ $1 != none ]]; then
  base_dir=$(cd "$1" && pwd)
fi
head_dir=$(cd "$2" && pwd)
mkdir -p "$3"
out_dir=$(cd "$3" && pwd)
accept=()
case "${PERF_ACCEPT_REGRESSIONS:-0}" in
  1) accept=(--accept-regressions) ;;
  0) ;;
  *) echo "PERF_ACCEPT_REGRESSIONS must be 0 or 1" >&2; exit 2 ;;
esac
summary=()
if [[ -n "${PERF_SUMMARY:-}" ]]; then
  summary=(--summary "$PERF_SUMMARY")
fi

run() {
  local side=$1 dir=$2 round=$3
  echo "::group::perf $side round $round"
  # Reparent tests roll back their writes, but still grow the physical tables. Stale
  # row estimates can cross jit_above_cost between rounds and add 50-70ms of compilation.
  # Reset both visibility and statistics before EVERY round, outside measured requests.
  psql -v ON_ERROR_STOP=1 -q "$PERF_PG_URL/test_perf_$side" -c "VACUUM (FREEZE, ANALYZE)"
  # SLOs are judged on the pooled median by compare.py, not per run: one noisy run must not fail the gate alone.
  (cd "$dir" && PERF_DATABASE_URL="$PERF_PG_URL/perf_$side" PERF_RESULTS="$out_dir/$side-$round.json" \
    PERF_SLO_ASSERT=0 uv run --frozen pytest perf --no-cov -q -s --ds=perf.settings --reuse-db -p no:cacheprovider)
  echo "::endgroup::"
}

# Seed each side before measurement. run() settles the database after the seed and
# again between rounds, since rolled-back write scenarios still change its physical state.
# One cheap scenario is enough: the session fixture seeds before any test.
seed() {
  local side=$1 dir=$2
  echo "::group::perf $side seed"
  (cd "$dir" && PERF_DATABASE_URL="$PERF_PG_URL/perf_$side" PERF_SLO_ASSERT=0 \
    uv run --frozen pytest perf --no-cov -q -s --ds=perf.settings --reuse-db -p no:cacheprovider -k "tag-playlist-list")
  echo "::endgroup::"
}

judge() {
  (cd "$head_dir" && uv run --frozen python -m perf.compare "$@" ${accept[@]+"${accept[@]}"})
}

if [[ $base_dir == none ]] || ! grep -q PERF_RESULTS "$base_dir/perf/conftest.py"; then
  if [[ $base_dir != none ]]; then
    echo "Base predates machine-readable perf results: no A/B comparison, head SLOs only."
    if [[ -n "${PERF_SUMMARY:-}" ]]; then
      echo "> ⚠️ The base branch predates the A/B perf gate: head judged on its SLOs only." >>"$PERF_SUMMARY"
    fi
  fi
  seed head "$head_dir"
  run head "$head_dir" 1
  run head "$head_dir" 2
  judge --head "$out_dir"/head-*.json ${summary[@]+"${summary[@]}"}
  exit $?
fi

seed base "$base_dir"
seed head "$head_dir"
rounds=0
measure() {
  for _ in 1 2; do
    rounds=$((rounds + 1))
    run base "$base_dir" "$rounds"
    run head "$head_dir" "$rounds"
  done
}

measure
if judge --base "$out_dir"/base-*.json --head "$out_dir"/head-*.json >/dev/null; then
  judge --base "$out_dir"/base-*.json --head "$out_dir"/head-*.json ${summary[@]+"${summary[@]}"}
  exit 0
fi
echo "Possible regression after $rounds rounds, measuring 2 more before the verdict."
measure
judge --base "$out_dir"/base-*.json --head "$out_dir"/head-*.json ${summary[@]+"${summary[@]}"}
