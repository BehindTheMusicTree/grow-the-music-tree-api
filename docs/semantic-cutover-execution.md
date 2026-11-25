# Semantic catalogue cutover execution

Resumed 15 November 2026 after PR #492 merged at
`389dd1b13061492173e5eb377f6e42ba43b6ec97`. The membership cutover merged in PR #503; the producer side remains.

## Invariant and scope

Each song has zero or one directly attributed semantic genre, with any number of
provenance decisions for that same genre. Every genre, whether its node has canonical state or not, has zero or one
canonical parent (the link selected for the displayed tree) and zero or more
noncanonical parents (other true subgenre links). Both participate in semantic
inheritance, with paths deduplicated. The contract represents the selected parent
with `displayParentId`, which must also be a `classification` or
`regional_membership` relation; the other relations retain the additional parents.
This choice is independent of the node's `canonicalState`, which controls canonical
and regional populations. Display selection does not remove semantic relations.
The public `song.genre` field remains singular and nullable.

Semantic attributions own membership. `Track.genre_id` must cease to drive Grow's
semantic queries and projections; synchronizing it as another authority would
retain the design flaw. Shared personal-tree behavior remains owned by Hear.

No graph activation, release, production deployment or change to pipelines PR #423
is authorized by this implementation. Keep the publication barrier until all
writers and readers below participate in the same transaction contract.

## Refreshed dependencies

Fetched before this continuation:

| Repository | Integration ref | Commit prefix |
| --- | --- | --- |
| Grow API | origin/develop | 389dd1b |
| genre-kit | origin/develop | 819655a |
| api-kit | origin/main | 83f87e9 |
| app-kit | origin/develop | b672524 |
| Grow frontend | origin/develop | f930f115 |
| pipelines | origin/develop | 12e777e |

App-kit `schemas/track/base.ts` and `schemas/song-search.ts` already expose a
singular nullable genre. Grow's refinement list reads `song.genre?.name`.
Pipelines integration has no semantic song-assignment transport yet. A consumer
contract change must be justified by source inspection rather than assumed.

## Implementation sequence

1. Establish one Grow membership query boundary over effective semantic
   attributions and permanent Genre bindings. Use it for direct assignment,
   unassigned songs and graph closure selections. Preserve active-node and
   regional-scope checks. Keep graph work bounded by graph size.
2. Convert exact catalogue and playlist buckets, artist summaries, summary input
   snapshots, search genre presence, serializers and refinement reads to that
   boundary. Exact buckets remain additive because direct assignment is unique;
   each selected semantic descendant contributes once. Snapshot data and cache
   tokens must be read together.
3. Route curation, undo, graph import/restore, TrackManager writes, deletion
   cascades, playability changes and playlist membership through the source gate
   before dataset and track locks. Attribution history, projections and revision
   changes commit or roll back together. Archive assignment state before SQL
   deletion, including full/delta stale rows.
4. Connect `assignment_write_transaction` and `publish_assignments` to the song
   merge. Populate `song_import(mbid, track_id, is_locked)`; derive semantic genre
   buckets from staged assignments rather than label/QID lookup. Validate reviewed
   graph/membership revisions under locks before song writes. Preserve locked
   assignments, explicit empty assignments, unaffected delta rows and song UUIDs.
   Validate manifests again at worker/recovery boundaries, including corrupted
   metadata and retries after commit.
5. Remove the unconditional legacy-only commit path only when steps 1–4 are
   coherent. Keep legacy imports explicitly rejected for an active reference
   graph. Do not infer missing revisions or silently fall back to old membership.
6. Document the producer contract and replay/rollback protocol. Make any necessary
   producer work in a separate task/worktree without editing PR #423. Preserve the
   singular frontend contract; change clients only where actual behavior requires
   it. Releases and activation require their own concrete approval.

## Validation and delivery

Test empty/one/multiple direct genres, multiple evidence decisions, overlapping
semantic ancestry, regional isolation, unassigned/unplayable songs, manual locks,
full/delta deletion, graph retirement/reactivation, undo, retry and atomic rollback.
PostgreSQL concurrency tests must exercise the common lock order and consistent
response snapshots. Compare returned songs, playable songs and exact/aggregate
counts across catalogue, playlists, search and artist endpoints.

Run the documented SQLite and PostgreSQL suites, Ruff, mypy and migration checks.
Use CI Perf, including its same-runner comparison; never waive red Perf or raise
budgets. Production-scale investigation is staging read-only through diag-vps.
Obtain independent review through create-pr-and-fix-ci before pushing nontrivial
implementation, deliver a ready PR and retain auto-merge under the existing policy.

## Current state: materialized song genre

The effective genre of a song is stored in `grow_song.genre_id`
(`Song.membership_genre`), not computed at read time (a read-time view made `Perf`
red). Migration `0140` installs the derivation (`grow_effective_genre`), the
triggers that keep the column current, the single-assignment guard and the
backfill; `0141`/`0142` derive the catalogue counts and buckets from the column.

- Derivation: without a `grow` dataset, the song's `Track.genre`; with one, the
  genre bound to the song's attribution on an active `grow` node, else `NULL`
  (a retired assignment never falls back to the legacy genre).
- Maintenance: triggers on attributions, nodes, criteria bindings, datasets and
  `Track.genre` refresh the affected songs; a `BEFORE INSERT` trigger fills new
  songs. The gate trigger takes the catalogue advisory lock (the one behind
  `lock_catalogue_sources`) and requires READ COMMITTED, so writers serialize.
  Writers that bypass the managed service path (admin, raw SQL) rely on the same
  triggers but not on the service lock order.
- Direct writes: a write to `genre_id` that differs from the derived value is
  rejected (`23514`) at trigger depth 1; clearing it (a genre delete's
  `SET NULL`) and restating the derived value are allowed. Once a dataset exists,
  `Track.genre` is ignored for membership.
- Data-model guards: an attributed node cannot be deactivated, a criteria's graph
  binding cannot be rebound, and a dataset with nodes cannot be deleted, so those
  trigger branches are reachable only after the attributions are removed.
- Verification: `song_membership_drift()` (`grow/genre_music/catalogue_verification.py`)
  recomputes the genre of every song in Python and reports songs whose stored
  column differs; `verify_catalogue_counts` checks the buckets.
- Tests: `tests/integration/criteria/test_song_membership_boundary.py` and
  `test_song_membership_triggers.py` (node retirement/reactivation, rebind and
  dataset guards, drift, direct-write rejection, attribution-versus-retirement
  concurrency on PostgreSQL).

The genre kit (v0.65.0) enforces one node per track and dataset with
`UNIQUE(dataset_id, track_id)`; migration `0144` drops grow's
`grow_single_assignment_guard`. Follow-up: the pipelines producer for the Gold
graph and assignments.

## Reviewed song runs and Perf seed

Legacy song runs are removed. Every songs run declares `graph_revision`,
`membership_revision` and `expected_parts` (`songs`, `assignments`), uploads both
kinds of parts (`PUT …/import-runs/<runId>/parts/<n>/` and
`…/assignments/parts/<n>/`) and commits only when both are complete (incomplete
commit: 400). Each imported song needs exactly one assignment row (`{}` when it
has no genre). A pipelines import without assignments is refused (400); the
pipelines producer must export the Gold graph and the assignments.

The Perf and dev seeds (`perf/gold_graph.py`, `perf/conftest.py`,
`scripts/seed_dev_db.py`) bridge the gap: they convert the pinned Gold trees into
a v2 graph, map identities to genre UUIDs through `wikidata_id` (never by label)
and derive one assignment per song. The conversion is approximate (no
polygenre). Resolution is strict: an unknown or ambiguous name is an error, a
canonical genre wins over a regional one with the same name (`new wave`), and the
only pinned exception is `UNRESOLVED_GENRE_NAMES = {"deathcore": 5}` (five songs
without genre; the seed fails if the set differs). Remove the exceptions once the
producer exports the Gold graph and assignments.

A genre's song list includes unassigned songs; `assign-genre` returns an `undoToken`, and `POST library/songs/assign-genre/undo/` restores the snapshot (#505).
