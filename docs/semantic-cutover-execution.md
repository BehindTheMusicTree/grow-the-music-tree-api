# Semantic catalogue cutover execution

Resumed 15 November 2026 after PR #492 merged at
`389dd1b13061492173e5eb377f6e42ba43b6ec97`. Implementation remains incomplete.

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

## Current progress

- Recovered into the main checkout on `feature/semantic-assignment-cutover-resumed`
  at the user's explicit instruction; preserve the original worktree as recovery material.
- Queried the existing graph for discovery and inspected current merge,
  publication, selection, projection and direct writer entry points.
- Confirmed the worker still calls `require_legacy_import_contract()`
  unconditionally; attribution write/restore currently do not refresh the legacy
  catalogue/search projection paths.
- The uncommitted membership boundary and import-contract checks have focused
  SQLite and PostgreSQL coverage. The boundary is not yet connected to the
  catalogue projections, remaining readers or all writers.
- Catalogue and playlist membership verification now aggregate through the
  boundary. Focused checks passed on SQLite (33 tests) and PostgreSQL (10 tests);
  projection maintenance itself still uses the legacy source.
- Genre-kit PR #279 merged the retirement fix; PostgreSQL CI exposed a test
  setup error after auto-merge. Follow-up PR #280 fixed it and passed both
  PostgreSQL driver jobs before merging. Kit v0.63.2 was approved, released in PR #281 and back-merged in PR #282; the Grow dependency and lockfile are updated locally.

## Resumed boundary validation

- PostgreSQL boundary suite: 15 passed, including concurrent raw writes and a
  reader snapshot held across committed reassignment. Refresh the fixture dataset
  before capturing the reviewed membership revision: assignment installation
  invalidates the revision on the database row. Worker exceptions now surface
  directly if the concurrency test fails to observe a commit.
- Focused Ruff lint/format and Django migration drift checks passed. PostgreSQL
  concurrency tests must be excluded from SQLite runs with `-m "not postgres"`.
- Projection migration design and implementation remain the next dependency; do
  not activate the graph or remove the import publication barrier.

## Catalogue projection draft

Migration 0140 reconstructs pre-statement membership from transition rows and
computes direct bucket deltas only for affected tracks. Dataset activation and
removal require the full population; ordinary revision changes skip this work.
Both PostgreSQL statement triggers and SQLite row triggers are included, with a
reverse path to the legacy projection. Focused regression tests cover raw
reassignment, clearing, obsolete legacy writes, deletion and rollback. Validation
runs in draft PR CI at the user's request. Playlist and search projections and
semantic bulk publication remain incomplete; keep this PR draft and retain the
publication barrier until the complete cutover has passed review and CI.

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

A genre's song list includes unassigned songs; server-side undo is tracked in #505.
