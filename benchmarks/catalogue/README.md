# Catalogue benchmark harness (inactive)

This package is the representative Grow catalogue benchmark: it restores an
approved catalogue into a disposable PostgreSQL 16, runs two Grow commits A/B
against it on a GitHub-hosted runner, and computes a paired-median verdict.
Only the `export_perf_catalogue` command imports it, the Docker image ships just
the subset that command needs (see "Export plan"), and no workflow runs a
benchmark yet: `catalogue-benchmark.yml` only tests the harness.

It was moved here from the `infrastructure` repository (`grow-perf/`, source
`origin/main` 2cae6769), where it had been written when the benchmark was meant
to run on the application VPS. Contract names (`btmt_grow_perf`, the
`grow_perf_*` roles, the `btmt.grow-perf.invocation` label) are unchanged.

## Ownership

| Repository | Owns |
| --- | --- |
| Grow (this directory) | harness, scenarios, workflow and verdict; the `export_perf_catalogue --plan` command |
| infrastructure | production export, sanitization and approval, and private delivery of the bundle |
| github-config | the required check, once the benchmark gates merges |

Images must be built away from the application VPS. The runner must have the
manifest's `runner` profile (`4cpu-16gb` for public-repository standard runners).

`manifest.py` validates a canonical root-owned JSON manifest, exact commit SHAs,
image digests, backup/scenario hashes and alternating A/B rounds. Its identity
binds all supplied values. Syntax validation does not prove image provenance or
that an image was built from the stated SHA. The trusted runtime must verify
those relationships and root approval before executing anything; `registry_image`
binds offline image IDs to registry manifests. `trusted_json` accepts an explicit
`maximum_bytes` bound (64 KiB by default).

`sanitization.py` validates an operator-reviewed schema hash, approved table
columns, selected TABLE DATA entries and supplied row/ownership observations.
It rejects private/operational table names and requires at least 30 million
songs. It is a restore-policy helper, not a sanitizer; `catalogue_restore` and
`restore_execution` apply it. When given `all_columns`, it also requires every
column of each table to be classified. The caller must supply a complete
database table inventory, including denied tables, and run these checks before
candidates receive access. No production schema policy or backup is approved.

`catalogue-schema.tsv` is the `information_schema` inventory of the migrated
`develop` schema (same query as `inventory_sql()`). The Postgres test
`tests/integration/benchmarks/test_catalogue_schema_contract.py` runs in the
required `Pytest` job and fails with a diff when a migration changes it:
apply the diff, then classify any new table as RETAIN, EMPTY, REBUILD or DERIVED.
Staging tables are UNLOGGED and `pg_dump` skips their data, so
`relation_inventory_sql()` tolerates UNLOGGED only for EMPTY tables. The
restore does not re-implement the derivation of `grow_song.genre_id` (from
`Track.genre_id` or the graph attribution); the executor verifies it after
restore with `grow/genre_music/catalogue_verification.py`.

DERIVED tables (`grow_song_search`, `grow_artist_song` and their state rows) are
projections that are slow to rebuild (song search takes hours at catalogue
scale). The restore keeps their data, pruned to the retained songs and artists
(their rows carry titles and names), instead of requiring them empty. Each state
row stores the fingerprint of the definition that built the table, so
preparation runs `migrate`, then `rebuild_song_search --if-stale` and
`rebuild_artist_song --if-stale`: a side whose code did not change a projection
keeps the data, and a side that did rebuilds it. A rebuilt table and a restored
one are both freshly written (data reloaded, indexes rebuilt), so their physical
state matches and the A/B comparison stays fair. REBUILD tables (the two
count tables) stay empty in the dump and are rebuilt by preparation. The
tree-version singleton is RETAIN: it holds one token row, and neither `migrate`
nor the count verifications recreate it.
Limitation: pruning drops derived rows of missing songs and artists but does not
recompute a retained song's search document, which aggregates its artists' names;
canonical songs only credit canonical artists, so no private name reaches it.

## Export plan

`manage.py export_perf_catalogue --plan` (read-only, runs no `pg_dump`) prints
the JSON plan the infrastructure export follows, so the table classification
lives only here. `export_plan.build_plan` returns `version`, `inventory_sha256`
(of the live `information_schema` inventory, not the schema SQL digest of the
sanitization policy), `data_tables` (RETAIN and DERIVED, dumped with data),
`schema_only_tables` (EMPTY and REBUILD) and `projections` (each DERIVED
projection's state table and stamped fingerprint). The command fails when the
live schema drifted from `catalogue-schema.tsv` or a projection is not stamped
with the deployed definition (`rebuild_song_search --check`,
`rebuild_artist_song --check`). The image ships `__init__.py`,
`catalogue_restore.py`, `export_plan.py`, `manifest.py`, `sanitization.py` and
`catalogue-schema.tsv` (`.dockerignore`);
`tests/unit/benchmarks/test_dockerignore_subset.py` keeps that list equal to the
command's import closure.

## Preparation

`prepare.py` runs once per side, as `grow_perf_owner` inside the side's own image, with
`DJANGO_SETTINGS_MODULE=grow_perf_settings` (inert secrets, `LocMemCache`, no `statement_timeout`, no network).
The same two files prepare the base and the head, so they only call commands both versions ship (a base older than `verify_song_membership` fails fast with `Unknown command`). It stops at the
first failure, logging a timestamped line per step:

1. check PostgreSQL 16, then `migrate`;
2. `verify_song_membership`: one set-based query, so a drifted dump fails before hours of rebuilds;
3. `rebuild_song_search --if-stale`, `rebuild_artist_song --if-stale`: a stale fingerprint rebuilds, there is no
   fallback for an image without `--if-stale`;
4. `verify_genre_membership_counts --repair`, then `verify_genre_catalogue_counts --repair`;
5. `VACUUM (ANALYZE)` of every `public` table, then a check that none lacks `last_analyze`. PostgreSQL 16 restores
   neither planner statistics nor the visibility map, and without them plans and index-only scans differ from prod.

The job timeout is the time left before the manifest deadline, so a long rebuild ends as an
`infrastructure_failure` with cause `deadline`; a failing script is cause `preparation`. Two restores plus a song
search rebuild may not fit a 6 h hosted runner: calibration decides.
`Preparation.script_sha256` and `settings_sha256` are the sha256 of these files at the harness SHA.
`tests/integration/benchmarks/test_catalogue_prepare.py` runs the script on PostgreSQL 16 in the `Pytest` job,
and `tests/unit/test_catalogue_prepare_script.py` covers its step order and gates there too: `prepare.py` imports
Django, which the stdlib-only harness suite below does not install.

## Runtime-independent benchmark core

These modules do not depend on how the application and PostgreSQL are hosted:

- `scenario_plan.py` pins scenario definitions and comparison policy into an
  immutable inventory; `scenario_execution.py` runs the pinned HTTP schedule over
  an inode-pinned Unix socket and checks response correctness.
- `measurement_evidence.py` rejects incomplete or inconsistent measurements.
- `controller.py` runs alternating AB/BA rounds behind a `Runtime` protocol and
  writes a durable receipt; the runtime adapter owns preparation and isolation.
- `performance_decision.py` computes the paired-median verdict; `reporting.py`
  recomputes it independently from retained evidence before accepting a pass.
- `catalogue_restore.py`, `restore_execution.py` and `restore_bundle.py` project
  and restore an approved catalogue dump with schema-drift refusal and
  transactional rollback; `database_handoff.py` applies the restricted candidate
  database privilege boundary after preparation.
- `private_files.py` holds the root-private path and directory fsync helpers.

The catalogue tests run against a disposable PostgreSQL 16 when
`GROW_PERF_PG_BINDIR` points at its binaries, as in CI (for example
`/usr/lib/postgresql/16/bin`); otherwise they skip.

## Hosted runtime

`hosted_runtime.py` runs both sides on a GitHub-hosted runner's Docker; `hosted.py`
is its CLI (`python -m benchmarks.catalogue.hosted`: `run` as root, `verify`
unprivileged). A version 2 manifest binds the
PR merge SHA, base and head images, catalogue, scenario and policy digests, the
pinned PostgreSQL image, the preparation scripts, the runner profile, a deadline
and the round count.

- Every container runs `--network=none`, read-only, `--cap-drop=ALL`,
  `no-new-privileges`, with memory, swap, pids and CPU limits, a numeric non-root
  uid and an invocation label. `docker inspect` is checked before start and the
  network namespace after it; image provenance is matched by `RepoDigests`.
- Each side is restored and prepared once: restore as `postgres`, move ownership
  to the NOSUPERUSER `grow_perf_owner`, run the side's own `prepare.py` as that
  role, then lock the owner and hand off to the read-only `grow_perf_app` role.
- Every round serves a `cp -a --reflink=always` clone of that prepared data
  directory (`reflink.py`), so no round sees an earlier round's writes or cache
  state and the restore is never repeated. The workspace must be on a filesystem
  with reflink support (XFS with `reflink=1`, btrfs); `prepare_side` probes it
  before the restore and fails fast, with no fallback to a byte copy. CI mounts a
  btrfs loop image (`GROW_PERF_REFLINK_DIR`) to exercise the real clone.
  Every round restarts PostgreSQL and the application and re-verifies the handoff.
- `verdict.json` is `passed`, `failed`, `inconclusive` or `infrastructure_failure`
  (cause `input`, `preparation`, `measurement`, `cleanup` or `deadline`). A cleanup
  failure overrides any measurement outcome. `verify` recomputes the decision and
  the evidence digest from the admitted manifest.

CI qualifies it with `tests/test_hosted.py` (fake Docker),
`tests/test_hosted_postgres.py` (PostgreSQL 16 handoff) and `qualification.py`
(real Docker isolation, root, disposable GitHub-hosted runner only).

## Synthetic catalogue

`synthetic/generate.sh <database-url> [scale-divisor]` fills a migrated, empty database with a synthetic catalogue
calibrated on aggregates read from staging (`synthetic/profile.json`, no row data): songs per artist, tracks per genre,
49% untagged tracks, genre graph depth and lineage size, playlist rel volume. Divisor 1 is the staging scale (31M songs);
`generate.sql` is seeded (`setseed`), so the same variables give the same rows. It is an alternative to a prod bundle
for catalogue benchmarks; it carries no prod data and no migration can invalidate it, since it is generated on the
current schema.

`tests/test_synthetic_catalogue.py` generates at 1/1000 scale twice into the database named by
`GROW_SYNTHETIC_DATABASE_URL` (migrated, empty; it is truncated) and checks determinism and the shape within 1.5x. The
children and subtree percentiles of the graph are not matched (the generator hits depth, lineage and max children, not
the p99 of children per genre). Fidelity at full scale (plans of the heavy queries against staging) needs a runner
sized like the capacity probe, not a laptop.

## Validation

From the repository root (the suite uses `unittest`, not pytest, and stays out of
`tests/` so Grow's pytest-django, SQLite and coverage settings do not apply):

```sh
uv run python -m unittest discover -s benchmarks/catalogue/tests -t .
GROW_PERF_PG_BINDIR=/usr/lib/postgresql/16/bin uv run python -m unittest discover -s benchmarks/catalogue/tests -t .
```

Tests cover the manifest and sanitization contracts, the runtime-independent
core and the hosted runtime (fake Docker and a disposable PostgreSQL 16 when
`GROW_PERF_PG_BINDIR` is set). They do not prove effective host isolation; the
`catalogue-benchmark.yml` workflow also runs `qualification.py` as root on a
GitHub-hosted runner for real Docker isolation.
