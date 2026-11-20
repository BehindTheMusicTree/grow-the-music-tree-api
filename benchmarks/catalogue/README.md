# Catalogue benchmark harness (inactive)

This package is the representative Grow catalogue benchmark: it restores an
approved catalogue into a disposable PostgreSQL 16, runs two Grow commits A/B
against it on a GitHub-hosted runner, and computes a paired-median verdict.
Nothing in the application imports it, the Docker image excludes it, and no
workflow runs a benchmark yet: `catalogue-benchmark.yml` only tests the harness.

It was moved here from the `infrastructure` repository (`grow-perf/`, source
`origin/main` 2cae6769), where it had been written when the benchmark was meant
to run on the application VPS. Contract names (`btmt_grow_perf`, the
`grow_perf_*` roles, the `btmt.grow-perf.invocation` label) are unchanged.

## Ownership

| Repository | Owns |
| --- | --- |
| Grow (this directory) | harness, scenarios, workflow and verdict; will own the `export_perf_catalogue` command (not created yet) |
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
apply the diff, then classify any new table as RETAIN, EMPTY or REBUILD.
Staging tables are UNLOGGED and `pg_dump` skips their data, so
`relation_inventory_sql()` tolerates UNLOGGED only for EMPTY tables. The
restore does not re-implement the derivation of `grow_song.genre_id` (from
`Track.genre_id` or the graph attribution); the executor verifies it after
restore with `grow/genre_music/catalogue_verification.py`.

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
  Every round restarts PostgreSQL and the application and re-verifies the handoff.
- `verdict.json` is `passed`, `failed`, `inconclusive` or `infrastructure_failure`
  (cause `input`, `preparation`, `measurement`, `cleanup` or `deadline`). A cleanup
  failure overrides any measurement outcome. `verify` recomputes the decision and
  the evidence digest from the admitted manifest.

CI qualifies it with `tests/test_hosted.py` (fake Docker),
`tests/test_hosted_postgres.py` (PostgreSQL 16 handoff) and `qualification.py`
(real Docker isolation, root, disposable GitHub-hosted runner only).

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
