#!/usr/bin/env bash
# Same-runner A/B perf gate: runs perf/ on the base and head checkouts in turn (base, head, base, head), each against
# its own seeded Postgres database, then judges the pooled results with perf/compare.py. Interleaving cancels the
# runner's drift, so a slowdown shows against the base instead of against a fixed threshold.
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
  # SLOs are judged on the pooled median by compare.py, not per run: one noisy run must not fail the gate alone.
  (cd "$dir" && PERF_DATABASE_URL="$PERF_PG_URL/perf_$side" PERF_RESULTS="$out_dir/$side-$round.json" \
    PERF_SLO_ASSERT=0 uv run --frozen pytest perf --no-cov -q -s --ds=perf.settings --reuse-db -p no:cacheprovider)
  echo "::endgroup::"
}

# Seeds a side's database (the import endpoints leave it with unvacuumed tables, so the first measured round ran 20-60%
# slower than the next ones on every search scenario) then vacuums it, so every measured round sees the same settled
# data. One cheap scenario is enough: the session fixture seeds before any test. pytest-django prefixes the database
# name with `test_`.
settle() {
  local side=$1 dir=$2
  echo "::group::perf $side seed and vacuum"
  (cd "$dir" && PERF_DATABASE_URL="$PERF_PG_URL/perf_$side" PERF_SLO_ASSERT=0 \
    uv run --frozen pytest perf --no-cov -q -s --ds=perf.settings --reuse-db -p no:cacheprovider -k "tag-playlist-list")
  psql -v ON_ERROR_STOP=1 -q "$PERF_PG_URL/test_perf_$side" -c "VACUUM (FREEZE, ANALYZE)"
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
  settle head "$head_dir"
  run head "$head_dir" 1
  run head "$head_dir" 2
  judge --head "$out_dir"/head-*.json ${summary[@]+"${summary[@]}"}
  exit $?
fi

settle base "$base_dir"
settle head "$head_dir"
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
