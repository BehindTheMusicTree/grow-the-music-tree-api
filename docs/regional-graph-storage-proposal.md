# Regional graph storage and catalogue cutover proposal

Investigation: 14 November 2026. Proposal only; the implementation and cutover remain incomplete.

## Recommendation

The design flaw is that mutable graph projections also carry identity lifetime and read synchronization. Closure ownership is implicit through a join; retiring a concept deletes its storage identity; serving a multi-query response requires an exclusive lock. Separately, Grow still maintains two competing definitions of a song's genre membership.

Fix those invariants in their owners: permanent semantic identities and dataset-owned selection indexes in genre-kit; snapshot reads and serialized writes; semantic attributions as Grow's sole genre-membership authority; queryset visibility enforced in api-kit. Keep graph-sized work in Python and catalogue-sized work in SQL. Preserve song and genre UUIDs, explicit decisions, provenance, and transactional rollback.

Use an atomic current-state closure with set-based replacement and MVCC reads. Immutable closure generations are a valid alternative, but they do not solve snapshot consistency for mutable song attributions or playlist membership on their own. They introduce additional publication and garbage-collection contracts without demonstrated benefit at the observed graph scale.

## Evidence and limits

Integration refs fetched before this proposal:

| Repository | Ref | Commit |
| --- | --- | --- |
| grow-the-music-tree-api | origin/develop | 9fafeba8d2a2e19b4cc5b310cf197da758533bec |
| the-music-tree-genre-kit | origin/develop | 330fe286ede8646ea5d6d6dc2253e097f7b7ff63 |
| the-music-tree-api-kit | origin/main | fc82ef54248f473cd95a283ce5efa9aead2453ac |
| hear-the-music-tree-api | origin/develop | d0267ab44aba2b6e60a73d34af555914fd39e15d |

The resumed Grow branch is `feature/regional-graph-boundaries` at `aafc8a8`, with unfinished retirement changes. Graphify was queried for discovery; source inspection supports the findings below.

- Genre-kit `genre_graph/storage.py:82` deletes closure rows through `ancestor__dataset`. Django generated `DELETE access WHERE id IN (SELECT access.id FROM access JOIN node ...)`, repeating the target table in the selection.
- The abandoned local test backend was still executing this statement after 10 minutes 50 seconds, with no lock wait. It was cancelled after confirming its test caller had disappeared. This establishes a stalled test statement, not production latency.
- A separate connection's non-executing `EXPLAIN` produced a nested-loop semi join over nested loops, with one-row estimates for both graph tables. Graph tables had no recorded analyze/autoanalyze. The populated test transaction was uncommitted, so externally reported zero live rows do not establish actual cardinality. The plan is a strong explanation for the failure mode, not a capture of the running backend's exact plan or a completed A/B proof.
- Genre-kit `genre_graph/models.py:39` gives access rows no direct dataset key. `storage.py:63` deletes absent nodes, and `storage.py:105` takes `FOR UPDATE` even for reads. The write context also delegates to the read context.
- Grow's 1,710-node regression imports, retires and restores a concept. Its extra scale nodes are isolated: it does not test closure density or heavily shared ancestry.
- The current import service still performs per-genre binding, metadata, playlist and parent writes. Fixing the closure delete alone does not establish that the full import scales well.
- Read-only inspection of the actual persistent staging API (`coolify.environmentName=staging`, resource `gtmt-api`, pull request `0`) found Grow migrations through `0128` and no graph tables. A live graph replay or plan comparison is unavailable without a deployment, which this investigation does not authorize.
- Api-kit `AppModelViewSet.get_object()` returns a manager lookup before applying `get_queryset()` or object permissions. Grow's current override adds another existence query to compensate. This belongs in api-kit.
- Grow `track/bulk_import/merge.py` still resolves genres by labels/QIDs and writes `Track.genre_id`; `song_search/rank.py:17` still defines genre presence from that column. `genre_music/selection_query.py` and `summary_inputs.py` still use display-tree/exact-bucket inputs. These contradict the new graph authority.

## Storage and transaction contracts

### Permanent identities

Keep one `GenreGraphNode` per `(dataset, identity)` for its full lifetime. Add explicit active/retired state; absence from the current graph retires it rather than deleting it. Reactivation reuses the node and consumer Genre UUID. Current closure rows and current attribution writes may reference only active identities.

Keep Grow's permanent semantic-identity-to-Genre-UUID binding. A retired Genre remains bound to its identity, with visibility determined by active state. Do not infer activity from a nullable relation once retired nodes are retained. Enforce immutable bindings and prohibit identity theft in the shared service and database constraints where expressible.

Every retirement requires a target identity or explicit null, plus decision ID, source and rationale. Archive affected assignments before remapping/clearing them. Preserve both the original provenance and the retirement decision. Each song has at most one directly assigned genre. Remapping that genre retains its evidence and the retirement decision. Reject incompatible evidence structures before mutation.

### Dataset-owned closures and set-based replacement

Add `dataset_id` directly to access rows. Enforce that the dataset, ancestor and descendant belong together with database constraints; a service-only check leaves direct SQL able to corrupt the index. Add indexes for dataset-scoped replacement and both ancestor-first selection and descendant-first attribution normalization. Check existing indexes before adding redundant ones.

Generate the desired `(dataset, ancestor, scope, descendant)` relation from the validated graph into a transaction-local staging table. Under PostgreSQL, stream it with COPY, analyze staging before joins, then delete obsolete rows and insert missing rows using dataset-scoped SQL anti joins. Update only changed node metadata. Unchanged payloads remain true no-ops. SQLite gets an explicit supported implementation with the same semantics; unsupported backends fail.

This removes the ORM-generated self-joining delete and avoids rewriting every unchanged closure row. Full regeneration of the desired graph-sized relation remains acceptable; its work is bounded by closure size, which can be quadratic in node count. It never enumerates song populations or all witness paths in Python.

Analyze written persistent tables inside the import transaction, following Grow's existing import convention. Statistics maintenance accompanies sound SQL shape; it is not the only defense against a pathological delete. Preserve the existing `WRITTEN_MODELS` validation for Grow merges and add equivalent coverage for kit-owned writes.

### Snapshot reads and serialized writes

Split read and write contexts instead of having one delegate to the other.

- Multi-query PostgreSQL reads use an outermost, read-only REPEATABLE READ transaction, established before the first query. Evaluate pagination, counts, serialization, graph metadata and revision headers within it. Readers do not lock the dataset row.
- Reject entry from an incompatible already-started transaction. Never silently continue under READ COMMITTED. Audit request wrappers and convert relevant concurrency tests to real transactions. Single-statement reads may retain statement snapshots when tokens and data are obtained together.
- Writes retain READ COMMITTED and the order `Grow source gate -> dataset rows in key order -> tracks -> attributions/projections`. Validate expected tokens after obtaining the relevant locks. Do not acquire exclusive locks from the read context.
- Require graph and membership tokens for reviewed membership mutations, including staged-import publication. Long uploads stage without holding publication locks; commit rechecks the reviewed graph and fails clearly if it changed.
- Ensure every mutation affecting a published population invalidates the relevant token in the same transaction. This includes attribution changes, song deletion, playability and playlist changes where their cached response depends on them.
- Snapshot lifetime ends with response materialization. No lazy queryset or streaming database access may escape it. Bound long reads and monitor vacuum retention; immutable generations would still need a policy for long-lived mutable-catalogue reads.

SQLite keeps an explicit transaction-based implementation for functional tests. PostgreSQL concurrency behavior must be verified on PostgreSQL; SQLite passing does not establish lock or MVCC correctness.

Cache keys include the graph revision, membership revision and applicable song/playlist projection revision, plus query/viewer scope. Cached inputs are reusable only when their tokens match the response snapshot. A process-global cache must not substitute current-state rows for an older snapshot.

## Owner changes and affected contracts

| Owner | Required change |
| --- | --- |
| genre-kit | Permanent identity lifecycle, dataset ownership constraints/indexes, staged closure diff, explicit read/write contexts, attribution history and normalization, statistics maintenance. |
| api-kit | Validate lookup syntax, resolve through the view's authorized queryset, apply the intended detail filter policy, and call object permissions once. Preserve existing error contracts. Test custom lookup fields, owners, public resources, hidden rows and denied object permissions. |
| Grow | Adopt active bindings and snapshot contexts; batch identity/projection writes; migrate every genre-membership read/write to semantic attributions; rebuild search/count/playlist projections and their invalidation from that authority. Remove the extra-query visibility workaround after adopting the api-kit fix. |
| pipelines | Define and emit semantic identity assignments plus explicit provenance, graph contract/revision and attribution deletion semantics; validate at export. Contract work is required, but this proposal does not authorize changes to pipelines PR #423. |
| Hear | Exercise shared-kit migrations and api-kit detail lookup behavior. Retain its personal-tree contract unless a demonstrated requirement needs a change; adopting semantic reference storage does not require converting its personal tracks. |

Grow song-import staging needs assignment rows separate from song rows to carry zero or one direct genre, explicit empty assignments and several provenance decisions for that genre. Validate all semantic references against the reviewed graph before publication. Full imports replace the declared assignment population; deltas modify only declared songs and explicit deletions. Preserve locked assignments, song UUIDs and unaffected rows. History and projection changes occur in the same transaction as the set-based merge.

Use `effective_attributions`/semantic access for catalogues, genre detail lists, playable playlists, distinct counts, search genre presence, refinement, artist summaries and link suggestions. A song with no assignments remains in the library. A song with multiple paths counts once; a regional expression cannot expose another region's population. Hand-authored playlist membership remains separate, but its genre-scoped views join the same authority.

Document the single direct genre response and mutation contract explicitly in serializers and downstream clients. Semantic parents may be multiple; inherited membership follows deduplicated graph closures. Identify affected app-kit/frontend consumers before implementing that contract change; their impact has not been exhaustively audited in this investigation.

Treat display parents as presentation. Do not keep a second genre authority by synchronizing `Track.genre_id`, display-tree traversal with the graph. Exact genre buckets remain additive over deduplicated descendant sets when they derive from the unique semantic assignment. Remove legacy authority dependencies from Grow's semantic path; shared personal-tree fields may remain for Hear's independently owned behavior.

## Alternatives and migration cost

| Approach | Benefit | Remaining cost or risk |
| --- | --- | --- |
| Direct SQL delete over dataset node IDs plus ANALYZE | Small immediate kit change; removes the target-table self join. | Still rewrites every closure row, retains identity deletion and reader serialization, and leaves Grow's competing membership authorities. Useful as an isolated repair, insufficient as the final cutover. |
| Dataset-owned current closure diff, permanent identities, MVCC snapshots | Fixes ownership/lifetime/read consistency together; changes only affected closures and catalogue projections; one transactional publication boundary. | Kit migrations, read-context changes, Grow import/projection work and contract tests. Snapshot nesting and long reads need explicit handling. Recommended. |
| Immutable closure generations and pointer swap | Supports prebuilt closures and retaining many published closure versions. | Readers still need a snapshot of mutable attributions, song state and playlists; otherwise those also need versioning. Adds generation-aware queries, retention and garbage collection. Reconsider if measured build/publish duration or historical graph querying justifies it. |

The recommended schema changes are moderate in the kit; the significant work is the already-required Grow catalogue/import cutover. Since persistent staging currently has no graph tables, there is no demonstrated existing graph-attribution population to migrate there. The initial catalogue conversion still processes the full song population in SQL and requires explicit mappings, an assignment backup and a measured maintenance window. Do not estimate elapsed time from the small local fixture.

Implement and review bottom-up without compatibility fallbacks: kit storage and api-kit correctness, then Grow consumers/imports, then the producer/client contracts needed for cutover. Coordinate with the separately owned catalogue-projection worktree; do not edit or duplicate its work. Deployments, package releases and real curation decisions remain separate user decisions.

## Validation and completion criteria

1. Kit PostgreSQL regressions cover a cold transaction with 1,710 nodes, import/retire/restore, overlapping paths and dense closures; inspect SQL shape and plans, not a brittle wall-clock-only assertion. Check active-state and cross-dataset constraint violations via direct SQL.
2. Two readers overlap without blocking each other. A writer can commit while a reader holds a snapshot; that reader returns the complete old state and matching tokens, and a new reader returns the complete new state. Test rollback, attribution changes, deletion cascades, playability changes and incompatible nested transactions.
3. Test stable song/genre/node identities, explicit-null retirements, merged evidence, reactivation, mapping theft, deleted songs, full/delta imports, locked assignments and failures after history writes. Rollback restores data, projections and tokens together.
4. Api-kit regressions establish queryset visibility and object permissions with no added existence query. Run Grow detail-query budgets and Hear's supported CI against the fix.
5. Compare semantic song sets, playable sets and distinct counts for canonical/regional/all scopes; cover unassigned songs, duplicate labels, multiple attribution paths and regional leakage. Check serializer and producer/consumer contracts.
6. Run Grow's complete pytest, Ruff/format, mypy, migration check, PostgreSQL suite and pinned Perf commands after implementation. Obtain an independent review through the review/PR skill family when ready. Do not push green fixtures as evidence of a completed cutover.
7. Production-scale performance evidence comes from staging read-only after an explicitly authorized deployment makes the schema available. Capture representative SELECT plans and buffers; assess write performance through authorized validation/CI rather than running a mutating EXPLAIN ANALYZE on staging. Never restore production locally or waive a red Perf check.

Current validation status: the prior PostgreSQL run did not complete; the SQLite log resumed from handoff has no final summary and its process has ended. Neither is a passing suite. This proposal changes documentation only; the existing dirty implementation is preserved and is not claimed ready to merge.

## Curation decision lists (grow#520)

The curation export carries regional graph decisions including `local_identities`, `canonical_roots`, `regional_memberships`, `regional_anchorings` and `regional_overview_types`. Every row has `decision_id`, `decision_source` and `reason`. Local identities have kind `genre` or `overview`. Curate a regional expression through the genre parent edge. Grow checks duplicate decisions, `LOCAL:` declarations and kinds, and membership cycles. The pipelines and genre kit check QIDs and classification cycles.
