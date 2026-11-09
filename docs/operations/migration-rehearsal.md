# Migration rehearsal

`scripts/rehearse-migration.sh` applies pending migrations to a disposable copy of the latest prod backup, reports what they cost, and destroys the copy. It never touches the local compose DB or any live database.

## When to run it

Before merging a migration that touches a large table (`grow_song` holds about 32M rows), takes a strong lock, or backfills data. Small schema changes do not need it.

Run it on a host with the disk and RAM for the dump (about 4x its size once restored, plus a second copy per run), outside CI hours. Use `--dump` with a file already on that host so R2 credentials never leave your machine; `--fetch-latest` needs `RCLONE_CONFIG` and `R2_BACKUP_BUCKET_NAME` (see [Prod data locally](../../README.md#prod-data-locally)).

## Inputs

- `--image`: the API image built from the branch, the one that would run `migrate` in the release phase.
- `--pg-image`: the same Postgres image as prod. The script aborts if the dump was made by another major version.
- `--pg-conf`: prod's `postgresql.conf`. Take the `db_postgres_conf` block for `gtmt-api` in the infrastructure repo's `ansible/playbooks/group_vars/all.yml` (`shared_buffers`, `max_wal_size`, `wal_compression`, ...).

## Examples

```bash
# Duration, WAL and locks of the pending migrations, cold cache, then a warm-cache run
scripts/rehearse-migration.sh --image gtmt-api:branch --pg-image postgres:16.4 --pg-conf ./gtmt.conf \
  --dump /srv/rehearsal/gtmt-api-db.dump --runs 2 --warm-sql ./warm.sql \
  --verify "python3 manage.py verify_genre_catalogue_counts"

# The migration must fail, and change nothing, while a reader holds ACCESS SHARE on grow_song
scripts/rehearse-migration.sh ... --hold-lock "grow_song:ACCESS SHARE" --expect-failure
```

`--target "grow 0114"` limits the migration, `--keep` leaves the containers up and prints the command that destroys them. Each run starts from a fresh `CREATE DATABASE ... TEMPLATE` clone of the restored dump, so runs are independent.

## Reading the report

Per run: migrations applied, cache state, duration, WAL written, temp file bytes, peak number of blocked lock requests, and the `--verify` result. WAL is measured after the clone, which writes the whole copy to WAL itself.

Treat timings as an order of magnitude. The restored database has no bloat and no traffic, and its page cache differs from prod's.
