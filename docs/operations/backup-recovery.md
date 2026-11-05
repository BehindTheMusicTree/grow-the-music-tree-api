# Recovering legacy Grow backups

Backups made before migration 0100 contain a search function whose unqualified dictionary reference can prevent ordinary `pg_restore` from creating the artist tables. Restoring such an archive requires the manual procedure below. The monthly drill must use an ordinary restore, not this procedure. Migration 0100 only fixes new dumps; it cannot change an existing archive. Reversing it restores the defective definition and should not be the default response to an application rollback.

Use a pinned, downloaded custom-format archive and a verified empty **disposable** database. Do not use `scripts/restore-prod-db.sh` for a legacy archive: it replaces the local schema before restoring. Protect the download and temporary lists, and do not modify the original object or archive. Record the object key, R2 timestamp and size, SHA-256, client and server versions, and the historical function definition in the recovery record. Confirm available disk space and archive identity before proceeding.

Set `ARCHIVE` to the downloaded file and `DEST` to the connection string for the empty scratch database. Supply credentials through the PostgreSQL environment or a protected password file, not command arguments or logs. Use compatible PostgreSQL client and server versions. Record `pg_restore --version`, `psql "$DEST" -c 'SELECT version()'`, and `shasum -a 256 "$ARCHIVE"`. Read the entire archive and stop if either command fails:

```sh
pg_restore -f /dev/null "$ARCHIVE"
pg_restore --list "$ARCHIVE" > restore.toc
```

Inspect the TOC and the schema-only function definition. Confirm exactly one `FUNCTION public grow_search_norm(text)` entry, the historical body `SELECT lower(unaccent('unaccent'::regdictionary, $1))`, and the `unaccent` extension prerequisite before that function. Confirm that the generated `grow_artist` and `grow_artist_alias` tables occur after it. Stop if any signature, definition, prerequisite or ordering differs. For example, inspect the definition without expanding the archive's data:

```sh
pg_restore --schema-only --function='grow_search_norm(text)' "$ARCHIVE"
```

Create two ordered `--use-list` files from the restorable (non-comment) TOC lines: the first contains every entry up to and including that function; the second contains all entries after it. Keep the lines unchanged. Verify that the lists are disjoint, their concatenation equals all non-comment lines of `restore.toc` in the original order, and that only the first list contains the function. Inspect both lists before continuing; a missing extension, generated table in the prefix, duplicate function or unexpected TOC layout is a reason to stop.

The following generates the lists and checks their structure; inspect the function definition and TOC as described above first. It aborts on a missing or ambiguous function, missing extension, or unexpected artist-table order.

```sh
python3 - <<'PYCODE'
from pathlib import Path

entries = [line for line in Path("restore.toc").read_text().splitlines() if line and not line.startswith(";")]
matches = [i for i, line in enumerate(entries) if " FUNCTION public grow_search_norm(text) " in line]
if len(matches) != 1:
    raise SystemExit("Expected exactly one public.grow_search_norm(text)")
split = matches[0] + 1
prefix, remainder = entries[:split], entries[split:]
if not any(" EXTENSION - unaccent " in line for line in prefix):
    raise SystemExit("unaccent extension must precede the function")
for table in ("grow_artist", "grow_artist_alias"):
    marker = f" TABLE public {table} "
    if any(marker in line for line in prefix) or sum(marker in line for line in remainder) != 1:
        raise SystemExit(f"Unexpected table ordering or count: {table}")
if set(prefix) & set(remainder) or prefix + remainder != entries:
    raise SystemExit("TOC partition is not disjoint and complete")
Path("prefix.toc").write_text("\n".join(prefix) + "\n")
Path("remainder.toc").write_text("\n".join(remainder) + "\n")
PYCODE
```

Restore the first list with `pg_restore --exit-on-error --no-owner --no-privileges --use-list=prefix.toc --dbname="$DEST" "$ARCHIVE"`. Confirm the function and `public.unaccent` function and dictionary exist. Replace the function in the destination only:

```sql
CREATE OR REPLACE FUNCTION public.grow_search_norm(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT pg_catalog.lower(public.unaccent('public.unaccent'::pg_catalog.regdictionary, $1)) $$;
```

Run the SQL using `psql -v ON_ERROR_STOP=1 "$DEST"`, then restore the remainder with `pg_restore --exit-on-error --no-owner --no-privileges --use-list=remainder.toc --dbname="$DEST" "$ARCHIVE"`. Do not retry by ignoring errors. Recheck the archive SHA-256 against the recorded value.

Verify artist and alias row counts against the expected source counts, stored folded names against `public.grow_search_norm`, and expected indexes and their `pg_index.indisvalid` state. Check constraints and record separately any pre-existing `NOT VALID` constraints and any unexpected missing or invalid constraints. Verify a schema-qualified normalization call with an empty `search_path`. Record counts, checks, versions, timing and cleanup. Preserve the evidence and remove only scratch resources created for this recovery.

If the recovered database is subsequently brought under Django management, apply migration 0100 through the normal migration process as a separate action. Do not alter migration history to claim it was already applied during this recovery.
