# Catalogue projection

The source is the canonical Song/Track join, including unplayable and genreless songs.
`grow_genre_catalogue_count` stores sparse exact-genre buckets, independently of
playlist membership. Missing zero buckets are intentional; missing required genre
playlists and the tree-version singleton are configuration errors.

## Readers and writers

Detail summaries and the genre playlist tree read this projection. Migration
`0138` removes the obsolete `CriteriaPlaylist.direct_songs_count` column and its
application maintenance. Deploy the matching application with the migration;
older application versions require reversing `0138`, which rebuilds their counts.

| Mutation | Projection owner |
| --- | --- |
| Song create | Song INSERT trigger joins parent |
| Genre reassignment, direct save or queryset update | Track UPDATE trigger joins child |
| Canonical/private owner change | Track UPDATE trigger |
| Child-only insert/delete/relink | Song transition trigger |
| Managed delete | First deleted MTI half removes joined contribution |
| Genre deletion or alias | Source reassignment and deletion triggers |
| Full/delta import | Statement transition triggers on SQL merge |
| TRUNCATE | Rebuild after truncation |
| Explicit repair | Independent aggregation under source gate |

PostgreSQL statement triggers aggregate net changes. Unrelated updates do not
rewrite catalogue buckets; existing triggers may still invalidate the shared tree
version for other projections. Both MTI halves participate so
the first deletion removes a song exactly once. SQLite uses equivalent row
triggers; it does not establish PostgreSQL concurrency correctness.

## Verification and repair

Run `uv run python manage.py verify_genre_catalogue_counts` with the normal app
configuration. This compares actual canonical Song rows with catalogue buckets. Drift produces a failing exit status without changing data.
`--database <alias>` chooses the connection.

`--repair` explicitly rebuilds the projection atomically, removes orphan catalogue
buckets, and independently rechecks before committing. Output retains pre-repair
findings. Invalid playlist configuration is rejected instead of manufactured.

Verification and repair require PostgreSQL READ COMMITTED isolation and acquire
the existing transaction advisory source gate before the tree-version row. Long
source transactions can delay them. Ordinary reads do not acquire this gate.

The song import takes the gate before reading its staging snapshot and holds it
until its merge commits, so manager-mediated edits cannot invalidate the snapshot's
membership and legacy deltas. This also makes those edits wait for the merge;
representative wait times and import overhead still need measurement.
The admin YouTube edit also takes the gate, after its YouTube lookup, because it
can set the manual-edit flag the import reads without any other source write.
The trigger gate does not cover Song-only updates to fields other than the
parent key, so any new writer of an import input must take the gate itself.

## Migration locks

Migration 0115 takes source relation locks before attempting the advisory gate.
Both acquisitions fail immediately when busy, rolling the migration transaction
back so it can be retried. This avoids waiting for an old writer that already
holds a relation lock while waiting at its BEFORE trigger. New writers wait for
the installation/backfill transaction to commit.

The backfill scans the Song/Track join under exclusive source-table locks, so
reads and writes on those tables block until the migration commits.

Measured on a restore of the 9 Nov 2026 production backup (32,075,219 songs,
22 GB), migrating the shadow migrations separately (numbered 0112/0113 on that copy, renumbered 0114/0115 after rebasing onto develop (migration 0113)) in a scratch Postgres 16:

| Step | Duration | WAL |
| --- | --- | --- |
| 0114 | 6.8 s | 1.6 MB |
| 0115, cold cache (first read after restore/clone) | 1,746 s | 8.6 MB |
| 0115, warm cache (join scanned once beforehand) | 97 s | 0.5 MB |

The join scan itself takes about 110 s warm; the cold figure is dominated by
reading the tables from disk. WAL is negligible because the backfill writes one
row per genre bucket. `verify_genre_catalogue_counts` reported zero mismatches
for both projections after the migration (15 min 43 s on that copy, read only).

Before deploying 0115 to an environment whose Postgres cache may be cold (after a
restart or restore), warm the join first, for example by running the `COUNT(*)`
of the Song/Track join once, so the exclusive window stays near 100 s instead of
tens of minutes. The deploy runs `migrate`; if a writer holds a source lock the
NOWAIT acquisition fails and the migration can be retried. Run
`verify_genre_catalogue_counts` after the deploy and before serving catalogue readers. Timings come from one VPS and one run each; treat them as an order of
magnitude, not a guaranteed window.
