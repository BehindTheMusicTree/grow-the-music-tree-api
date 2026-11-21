#!/usr/bin/env bash
# Generate the synthetic catalogue into a migrated database. Usage: generate.sh <database-url> [scale-divisor]
# Scale divisor 1 is the staging scale of profile.json; 100 gives a quick small catalogue for local checks.
set -euo pipefail
url=$1
d=${2:-1}
here=$(cd "$(dirname "$0")" && pwd)
psql "$url" -q -v ON_ERROR_STOP=1 \
  -v songs=$((31280773 / d)) -v artists=$((1943964 / d)) -v albums=$((4335938 / d)) \
  -v genres=6133 -v tagged_genres=1641 -v rel_stride=48 \
  -f "$here/generate.sql"
