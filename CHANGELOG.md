# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## Guidelines for Contributors

- Add entries to the `[Unreleased]` section under the appropriate category: `Added`, `Changed`, `Improved`, `Deprecated`, `Removed`, `Fixed`.
- Group related changes together; write clear, user-focused descriptions rather than raw git log dumps.
- Mention tests within the related feature or fix entry — "Test" is not its own category.

## [Unreleased]

### Fixed

- The genre reparent latency SLO test always moves the same genre and never picks a pop-side one, which the API rightly rejects under a root that already has a pop child. It used to pick a random genre and failed intermittently with 400.

### Added

- Region map snapshots: the pipeline uploads the region map index and GeoJSON files through `regions/map/import-runs/` (the chunked songs/artists protocol), grow stores each file once by content hash and swaps the active snapshot atomically, keeping the previous one. `GET /v1/regions/map/` serves the index with an `ETag` and `304`, `GET /v1/regions/map/files/{sha256}/` serves each file gzip-compressed and cached as immutable. Migration `0086` adds the tables and the `region_map` import kind. Tested on SQLite and, for the merge, on Postgres.

## [14.5.0] - 2026-10-29

### Added

- Genre playlists expose `viewsCount`, the sum of the YouTube view counts of the playable songs behind `tracksCount`, on the list, detail and `genre-playlists/tree/` payloads so clients can size the genre tree by views. Migration `0085` adds `CriteriaPlaylist.views_count`, backfills it, and keeps it current with database triggers (statement-level on Postgres) on playlist rels and `grow_song.youtube_view_count`, so the songs merge, curation edits and cascade deletes all stay in sync and the cached tree refreshes on its own. Tested on SQLite and, for the merge, on Postgres.

### Security

- Bumped `the-music-tree-genre-kit` to v0.52.1: genre tree import and `Genre.summary_source_url` now accept only `http(s)` URLs (migration `0084` records the validator). Covered by `tests/integration/criteria/test_summary_source_url_import.py`.

## [14.4.1] - 2026-10-29

### Changed

- The ambiguous MusicBrainz tags `r&b` (Rhythm and blues by default, with blues/jazz hints) and `trap` (trap music by default, EDM trap music alongside electronic dance music) are now seeded in the `genre_disambiguation` and `genre_disambiguation_context` curation lists (migration `0083`; seed CSVs updated to match, covered by the existing seed round-trip tests).

## [14.4.0] - 2026-10-29

### Security

- Artist bulk import now rejects link URLs that are not `http(s)`, so a `javascript:` or `data:` link can no longer reach the artist panel (image URLs were already checked). Covered by `tests/unit/bulk_import/test_artist_part_loader.py`.

### Changed

- Core electronic's 49 direct children are now split under its two scene nodes: 9 under Electronic dance music (commercial), 40 under Underground electronic (migration `0082` rewrites their `main_parent` curation entries; `manual_main_parent.csv` seed updated to match, covered by the existing seed round-trip tests).

### Added

- `GET /v1/artists/<uuid>/genre-counts/` (public) returns `[{genrePlaylist, songsCount, tracksCount}]` for the genre playlists whose subtree holds one of the artist's songs (ancestors included, Genreless for genre-less songs), so the genre tree can be pruned to an artist's footprint. `songsCount` counts all songs, `tracksCount` the playable ones. At most 3 queries. Tests in `tests/integration/artist/test_artist_genre_counts.py`, `tests/integration/perf/test_query_budgets.py` and `perf/test_latency_slo.py`.
- Song and artist import merges return `stepTimings` (`[{label, rowcount, ms}]` per SQL step) in their task result, so the import status endpoint shows where a merge spends its time. Tests in `tests/integration/track/song/test_song_import_runs.py` and `tests/integration/artist/test_artist_import_runs.py`.
- Artist detail exposes a nullable `image` (`{url, pageUrl, author, license, licenseUrl}`): a 500 px Wikimedia Commons photo, imported from the Gold artists' `image` key (parts without it import as no image). Showing it requires its attribution (author and license, linked to `pageUrl`); `author` and `licenseUrl` can be null; `url` and `pageUrl` must be https, `licenseUrl` http(s). Migration `0081` adds the columns with an `artist_image_complete` constraint. Tests in `tests/unit/bulk_import/test_artist_part_loader.py`, `tests/integration/artist/test_artist_import_runs.py`, `tests/unit/serializer/model/artist/test_detailed.py` and `tests/unit/model/artist/test_artist.py`.

### Improved

- Song import merge carries only new, adopted and changed songs (title, genre, YouTube fields, year, artist credit) through its write steps, and the artists import updates and inserts artists and albums with set-based statements instead of `ON CONFLICT`: an unchanged run no longer pays for the whole staged volume. Tests in `tests/integration/track/song/test_song_import_runs.py`.

### Fixed

- A song or artist import-run part or deletions upload cut short (client disconnect, or fewer bytes than `Content-Length`, or a malformed one) now answers 400 instead of 500 or a later invalid-gzip error; covered by unit and action-level tests.

- Import-run part and deletions uploads are read fully into a spooled temp file before the `COPY` starts, so a slow or truncated upload no longer runs inside the statement and trips the web `statement_timeout` (seen as 502s on 19 MB song parts). A truncated body still returns 400 `body is not valid gzip`. Tests in `tests/unit/view/test_bulk_import_spooled_body.py`.

## [14.3.0] - 2026-10-28

### Added

- Genres expose a nullable `scene` (`commercial` | `underground`), curated through the new `canonical_genre_scene` gold list and imported with the tree (genre-kit 0.52.0). Electronic dance music (`commercial`) and the new `Underground electronic` node (`underground`) now sit side by side under Core electronic. `scene` is on genre and genre-playlist outputs and filterable on `genres/`. Migration `0080` seeds the curation rows; `scene` and the new node reach genres at the next pipeline tree import. Tests in `tests/integration/curation/test_scene.py`.

## [14.2.0] - 2026-10-27

### Added

- Gold curation lists `genre_disambiguation` (candidate genres of an ambiguous MusicBrainz tag such as `r&b`, at most one flagged `is_default`) and `genre_disambiguation_context` (a context genre that, on a song, points the tag to one candidate): editable through the curation endpoints and included in the curation export as `manual_<list>.csv`, with `context_item_id` as an item id column. Tested in the curation API suite.

## [14.1.1] - 2026-10-27

### Fixed

- **Prod deploy rolling back on slow migrations**: migrations now run as a CI release phase instead of at container start
  - `build-and-deploy.yml` runs `manage.py migrate` once per deploy, from the exact image digest, with the app's current Coolify env, before Coolify is triggered; `start-server.sh` only runs `migrate --check`
  - Migration `0075` is idempotent on PostgreSQL, so the half-applied run left on prod by the killed deploys resumes instead of failing on `column "folded_name" already exists`

## [14.1.0] - 2026-10-27

### Added

- Songs carry the video's YouTube view count: the song import accepts an optional non-negative `youtube_view_count` (null when unknown), stored on `Song` and exposed as `youtubeVideo.viewCount`; a curator changing a song's video resets it. Tested for import (full and delta), validation, listing and curation.
- Genealogy snapshot: `POST genealogy/import/` (pipeline key or admin) validates the pipeline's `4_genealogy.json` (`columns`, `bands`, `successions`, `traditionLinks` lists; `traditions` items with `wikidataId`, `label`, `start`, `end`, `anchorId`, `inCanonicalTree`) and stores it whole as a `GenealogySnapshot` with its sha256 checksum, recorded as an `ImportRun` of kind `genealogy` for pipeline imports (admin imports are not recorded); an unchanged checksum creates no snapshot (200 instead of 201). Public `GET genealogy/` returns the latest document with `ETag` = checksum and `304` on `If-None-Match`. Tested in the genealogy suite.
- `curator` role: a second static key, `CURATION_API_KEY`, lets an agent read and write `curation/<list>/entries/` (history attributes its writes to the `curation-bot` user) without the admin Google token. The pipeline key keeps its export-only scope. **BREAKING:** `CURATION_API_KEY` is a required env var; set it before deploying.
- Geohistory curation list `entity_additions` (QIDs only): Wikidata items the `geohistory` pipeline ingests as cultural entities although no bulk class covers them, such as an archaeological site or a historiographical region. Tested in the curation API suite.
- Geohistory curation lists `tradition_additions`, `tradition_exclusions`, `tradition_placement_overrides` and `tradition_link_overrides` (Wikidata QIDs, `kind` `lineage|association`, `action` `add|remove`, a blank placement field keeps the derived value): editable through the curation endpoints and included in the curation export as `manual_<list>.csv`, with a `tradition_id` column kind and tests.

### Changed

- `Artist.recording_count` (`recordingCount`) counts every song crediting the artist, playable or not, instead of playable ones only: an artist whose songs have no video yet (Bob Marley) no longer shows 0 nor ranks below artists with a single matched song in artist search. A migration backfills existing artists; the songs import keeps it current. Tested against Postgres.

### Improved

- Artist search (`/v1/artists/search/`) answers in tens of milliseconds instead of 3-8 seconds: artists and aliases keep a stored folded name (`folded_name`) behind trigram indexes, the name and alias matches are two index-driven queries merged and deduplicated instead of one full-table scan with per-row subqueries, and results are cached in Redis for an hour (dropped when an artist import merges). **Deploy note:** migration `0075` adds stored columns, which rewrites `grow_artist` and `grow_artist_alias` under an exclusive lock (about a minute on production), so apply it outside an artist import run. Tested against Postgres (deduplication across name and aliases, cache hit, invalidation by import).

### Fixed

- Reparenting a genre onto one of its additional primary parents drops that edge instead of returning a 400, and the `secondary_parents` `add` rule of a secondary edge that became the main parent is dropped even without an actor (it would make the pipelines' gold export raise).

## [14.0.0] - 2026-10-26

### Removed

- **Breaking:** the `/v1/library/recordings/` and `/v1/library/youtube/` route aliases; use `/v1/library/songs/`.
- **Breaking:** the genre `essentialTracks` output and input key; use `essentialSongs`.

## [13.2.1] - 2026-10-26

### Fixed

- Reparenting a genre onto one of its secondary parents drops that edge and its `secondary_parents` `add` rule (it was rejected with a 400 before); a `remove` rule is kept, so it applies again if the main parent later moves away.

## [13.2.0] - 2026-10-26

### Changed

- Renamed grow's catalog entry `Recording` to `Song` and a genre's `essential_tracks` to `essential_songs`, matching the glossary (a Recording is only the MusicBrainz entity). Migration `0072` renames the model and table (`grow_recording` to `grow_song`), the genre field and its through table, and the `recording_genre` / `essential_tracks` curation lists to `song_genre` / `essential_songs` (reversible). `musicbrainz_recording_id` is unchanged. Tests moved to `tests/integration/track/song/`.
- `/v1/library/songs/` is the canonical route; `/v1/library/recordings/` stays as a legacy alias for one release.

### Deprecated

- `/v1/library/recordings/`: use `/v1/library/songs/`. To be removed in the next release.
- Genre output `essentialTracks` (a duplicate of `essentialSongs`) and input `essentialTracks` (`essentialSongs` wins when both are sent). To be removed in the next release.

## [13.1.1] - 2026-10-26

### Fixed

- `GET /artists/search/` no longer authenticates the request, so a bearer token from another BTMT app (e.g. hear) is ignored instead of rejected.

## [13.1.0] - 2026-10-26

### Added

- Geohistory curation lists `entity_exclusions`, `entity_membership_overrides` and `entity_time_span_overrides` (entity ids are Glottocodes or Wikidata QIDs, years are optional integers): editable through the curation endpoints and included in the curation export the geohistory pipeline reads, with `entity_id` and `int` column kinds and tests.
- Artist search data: `Artist.disambiguation` and `Artist.recording_count` (playable recordings, refreshed by the song import), an `ArtistAlias` model, and trigram GIN indexes on the accent-folded artist and alias names (`pg_trgm` + `unaccent`, built concurrently). The artist bulk import accepts optional `disambiguation` and `aliases` and resyncs them per artist. Postgres tests cover the alias round-trip, stale deletion, validation and `recording_count`.
- `GET /artists/search/?q=&limit=`: public, throttled artist typeahead over names and aliases (accent-insensitive, typo-tolerant, ranked by exact, prefix, similarity, then `recordingCount`); special-purpose artists are excluded. Tested against Postgres.

### Changed

- Genre searches by `name` (e.g. `GET /genres/?name=techno`) list the best matches first — exact, then prefix, then contains — so a short exact match such as "Techno" is no longer pushed past the first page by "Acid techno"; genre-kit 0.51.0.

### Fixed

- Moving a genre with hundreds of tracks under a large parent (e.g. Contemporary R&B under Pop hip-hop) no longer hits the 30s worker timeout and returns a 500: genre-kit 0.50.1 moves tracks with set-based SQL. A query-budget test (constant query count) and a Postgres latency SLO guard the reparent.

### Added

- Wikidata item catalog: `POST curation/wikidata-items/` (pipeline) replaces a `WikidataItem(item_id, label)` table holding every item the pipeline knows, pruned and `LOCAL:` ones included; `GET curation/items/?q=` (admin) searches items by name or id across the canonical tree, the catalog and pending additions. Tests cover push, replace, validation, auth and search.
- Curation lists expose `columnSpecs` (`{name, kind: item_id|bool|text, optional}`) and the history response a `labels` map, so clients no longer hardcode column kinds or show bare QIDs.

### Changed

- Curation item names are resolved by one function: canonical tree name, else catalog label, else the name given to a pending addition; entries, rules and history all use it.
- **Breaking:** curation lists no longer carry the derived names `item_label`, `parent_label` and `recording_label` (rows, CSV headers, seeds); they are resolved from the catalog or the tree. In `canonical_parent_additions` and `regional_overview_additions`, which create a node, `item_label` becomes `label`. A data migration rewrites existing entries, and the admin edit paths stop filling the names. Tests updated.

## [13.0.2] - 2026-10-22

### Improved

- The large track, track-artist and recording tables get absolute autovacuum/autoanalyze thresholds (200k/100k changed rows) instead of the default 20%/10% scale factors, which a nightly delta merge never reached on ~30M-row tables, so they were never vacuumed or analyzed.
- The songs import merge no longer scans every owner track to match staged songs, and re-syncs track artists in one scan instead of two, cutting about 1 min 30 s off a 500k-song delta.

### Fixed

- The Docker image now includes `wget`, so Coolify's healthcheck fallback no longer logs "wget: not found".

## [13.0.1] - 2026-10-22

### Fixed

- Migration 0065 no longer aborts the deploy when a `genre_precedence` name has no canonical genre: names also resolve through the " music" suffix, and pairs naming an unresolvable genre are dropped with a warning.

## [13.0.0] - 2026-10-22

### Breaking

- Curation list `umbrella_canonical_genres` renamed `non_stylistic_genres` (appellations without a coherent style, still dropped from the canonical tree); entries and review items are migrated, and `curation/export/` serves the new name.
- Curation list `genre_precedence` is now keyed by Wikidata ids (`item_id`, `over_item_id`, `reason`) instead of MusicBrainz tag names. Migration 0065 converts existing entries via canonical genre names then `genre_alias`, drops pairs already in a lineage, and fails listing any name it can't resolve.

### Added

- Umbrella genres: `Genre.is_umbrella` (canonical genres kept only to group sub-genres), set from the tree import's `isUmbrella` (`the-music-tree-genre-kit` v0.49.0) and exposed as `is_umbrella` on genres, genre playlists and the tree endpoint, with `?is_umbrella=` on genres.
- Curation list `umbrella_genres`; an entry for a genre with no sub-genre is rejected.
- Assigning a recording to an umbrella genre is rejected with a 400.
- `GET recordings/?genre_is_umbrella=true` lists the recordings still to refine.

### Fixed

- SQLite test databases lost the `grow_genre` tree-version triggers when `is_umbrella` was added; migration 0064 recreates them.

## [12.16.0] - 2026-10-20

### Fixed

- Local `docker compose up` crashed at startup with `KeyError: 'WEB_DB_STATEMENT_TIMEOUT_MS'`: the dev override now sets it (30000, same as production).
- `the-music-tree-genre-kit` bumped to v0.48.1: bulk inserts chunk by the connection's parameter limit (999 on SQLite, 65535 on Postgres), and a genre summary source URL without a summary is rejected. `test_largest_then_ok` is back to 3000 rows. A test pins that clearing a genre summary upserts a `summary_overrides` row with an empty summary, nulls `summary_source_url` and locks the genre.

## [12.15.0] - 2026-10-20

### Fixed

- A songs or artists import merge lost to a worker restart (a redeploy killed the django-q2 worker mid-merge; the Redis broker never redelivers) is enqueued again by the next import status poll, instead of staying `pending` forever. `BulkImportRun` records `started_on`, `user_id` and `record`; the merge holds a per-run Postgres advisory lock, so a free lock on a started run means its worker died. `task_id` is now the run's task group (`import-run-<runId>`). Postgres tests cover requeueing a lost merge and leaving a merely queued one alone.

### Added

- `GET genres/<uuid>/overview/` returns `description` (Wikidata short description) and `summarySourceUrl` (the Wikipedia page the summary came from; `null` for non-genre criteria). An admin summary edit clears `summary_source_url`, so a hand-written summary carries no Wikipedia attribution. Bumps `the-music-tree-genre-kit` to v0.48.0 (migration `0063` adds the two genre columns). Tests cover the overview fields and the attribution being cleared.
- `POST curation/wikidata-resolutions/` review items accept an optional validated `evidence` (the item's current Wikidata label, last edit, P31/P279 values, whether it has a P2341, the colliding curation list), and `GET curation/review/` returns it, so the admin can see why a rule was dropped. Integration tests cover the round trip and rejected keys.

## [12.14.1] - 2026-10-19

### Fixed

- Canonical tree import no longer fails with "Post-apply state does not match the imported payload" when a QID also exists in the regional tree (`the-music-tree-genre-kit` repinned to v0.47.1).

## [12.14.0] - 2026-10-19

### Added

- Each assign-genre `previous` item carries `undoable` (false when the previous genre has no wikidata id, so no curation list can restore it).
- Delta mode for the songs and artists import runs: `POST …/import-runs/` accepts `{"mode": "delta"}`, and `PUT …/import-runs/<runId>/deletions/` takes the gzip NDJSON ids to delete. A delta merge upserts only the uploaded rows and deletes only the listed ones (locked tracks and credited artists stay), instead of deleting everything missing from the run, so the nightly sync no longer re-sends the whole catalog. Full mode is unchanged. Postgres integration tests cover both kinds.

### Fixed

- Editing a recording's YouTube video now records the actor and an `UPDATED` history entry.
- Aliasing a genre to one of its own descendants is rejected with 400 (also in the preview); moved essential tracks are now written as curation rules.
- `PUT` on a genre only writes summary/essential-tracks rules and locks the genre when those values actually changed. Tests cover each.

## [12.13.0] - 2026-10-19

### Added

- Admin curation endpoints (IsAdmin): `POST library/recordings/assign-genre/` (returns `previous` for Undo), `PATCH library/recordings/{uuid}/` for `youtubeVideoId` / `youtubeUnplayableReason` (YouTube Data API lookup), `GET library/recordings/search/`, `GET genres/{uuid}/link-suggestions/`, `POST`/`DELETE genres/{uuid}/secondary-parents/{parentUuid}/`, `POST genres/{uuid}/alias-of/` with `GET .../alias-of/preview/`, and `summary` / `essentialTracks` on `PUT genres/{uuid}/`. Each edit is recorded as a curation rule so pipeline syncs keep it; integration tests cover each endpoint.
- Curation lists `recording_genre`, `recording_youtube_video`, `essential_tracks`, `summary_overrides` and `secondary_parents`.
- Required `YOUTUBE_API_KEY` setting (fails fast when missing).

### Changed

- `regional_secondary_parents` is merged into `secondary_parents` (migration 0058 moves existing rows).

## [12.12.0] - 2026-10-19

### Added
- **Curation Wikidata resolutions**: `POST curation/wikidata-resolutions/` (`X-API-Key` or admin) remaps curation entries whose item id Wikidata redirected, with history (null actor), and stores the ids the pipeline couldn't resolve (redirect conflict, deleted, not in tree) as review items, replaced on each report (model `CurationReviewItem`, migration `0057`). `GET curation/review/` (admin) lists them. Tests: `tests/integration/curation/test_wikidata_resolutions.py`.

## [12.11.0] - 2026-10-19

### Added

- **Pipeline runs**: kind `sync` (admin-only, never superseded) replays the last complete Gold output into grow, and stages `uploading_artists` and `merging_artists` report the artists import (migration `0056`). Tests: `tests/integration/import_run/test_pipeline_run.py`.
- **Curation export**: `GET curation/export/` returns `exported_on` (ISO 8601), the export's instant, recorded as the last export when the pipeline key fetches it.

### Changed

- **Genre tree import**: an `X-API-Key` import requires `curationExportedOn`, the curation export its Gold was built from, and sets `applied_export_on` to it, so replaying an older Gold leaves later edits pending. 400 if missing, unparseable or later than the last export. Admin imports are unchanged. Tests: `tests/integration/curation/test_curation_status.py`.

## [12.10.3] - 2026-10-16

### Fixed

- **Artists import**: the merge now scales linearly with run size. The old one timed out on 1.87M artists (django-q 14400 s) from `NOT IN` over unindexed temp tables and per-step re-expansion of the JSON arrays. Each array is expanded once into typed, keyed, ANALYZEd temp tables; children are diffed against the desired set (an unchanged re-run deletes and inserts nothing); stale artists are found with `NOT EXISTS`. Test: `tests/integration/artist/test_artist_import_merge_scaling.py` (4x the rows must take under 14x the time, best of two; the old merge took 26x).
- **Bulk imports**: django-q kills a timed-out merge without running its cleanup, leaking its staging rows and committed run. Creating a run now also sweeps committed runs older than twice the task timeout (a queued run may wait one full merge before it starts). Test: `tests/integration/artist/test_artist_import_runs.py`.

### Changed

- **Bulk imports**: a `LOGGING` config sends the `grow.bulk_import` logger at INFO to the console; every merge step logs its rowcount and duration (`bulk import step <label> rowcount=<n> in <ms> ms`), for songs and artists.
- **Artists import**: link URLs are capped at 2048 bytes (400 above), so the new `ArtistLink (artist, kind, url)` unique constraint (migration `0055`) stays within a btree key. Identical duplicate memberships collapse to one row only for rows written by the new merge; existing duplicates in the database are not removed.

## [12.10.2] - 2026-10-15

### Fixed

- **Bulk imports**: a large part PUT (a 250k-row, 200 MB artists part) got the gunicorn worker OOM-killed under the 256 MB limit. On Linux psycopg does not flush COPY data, so libpq buffered every row Postgres had not consumed yet, up to the whole part. `copy_part` now waits for each 128 KB chunk to reach the server, so peak memory no longer grows with part size (355 MB part: 388 MB peak RSS before, 110 MB after). Covers songs and artists parts. Test: `tests/integration/artist/test_artist_import_runs.py`.

## [12.10.1] - 2026-10-15

### Fixed

- **Artists import**: release-group titles longer than 256 characters (real MusicBrainz titles reach 890) failed the whole part with 400. `ALBUM_NAME_LEN_MAX` is now 2048, matching artist names and track titles, so titles are stored verbatim. Migration `0054` widens `Album.name` (metadata-only in Postgres). Tests: `tests/integration/artist/test_artist_import_runs.py`.

## [12.10.0] - 2026-10-15

### Added

- **Reliability**: gunicorn web workers set a Postgres `statement_timeout` from the required `WEB_DB_STATEMENT_TIMEOUT_MS` env var (read in `grow/wsgi.py`, so `migrate` and the import cluster are unaffected). A cancelled query returns 503 `query_timeout` instead of hanging until gunicorn's SIGKILL. Test: `tests/unit/view/test_exception_handler.py`.

### Changed

- **Recordings**: `library/recordings/?withTotal=false` without `page` now paginates by keyset cursor over `(genre, uuid)` (requires `genre`; `ordering` and `from` are rejected with 400), so each page is one index range scan at any depth instead of an OFFSET walk over ~31M rows. `next` carries an opaque `cursor`; `page`, `totalPages` and `overallTotal` are `null`. With `page` the OFFSET path is unchanged. Bumps genre-kit to v0.47.0 (`(genre, uuid)` index, migration `0012` builds it concurrently) and api-kit to v0.10.4. Tests: `tests/integration/track/recording/test_list.py`.

## [12.9.2] - 2026-10-15

### Fixed

- **Recordings**: `library/recordings/?withTotal=false` returned 400 `invalid_filter` in prod, because `CamelToSnakeMiddleware` rewrites the param to `with_total` before the filterset and pagination see it. `NO_TOTAL_PARAM` is now `with_total`. `tests/settings.py` now shares prod's `MIDDLEWARE` (`grow/middleware_settings.py`), so tests exercise the same query-param rewriting. Test: `tests/integration/track/recording/test_list.py`.

## [12.9.1] - 2026-10-15

### Changed

- **Songs import**: each NDJSON line must carry `first_release_year` (integer 0..32767, or `null` when unknown); a line without the key is rejected (400, nothing staged) instead of silently nulling the stored year. Pipelines Gold v6.2.0+ always writes it. Test: `tests/integration/track/recording/test_song_import_runs.py`.

### Fixed

- **Recordings**: `albumYear` ordering only falls back to four-digit album years, so an album year like `"70"` no longer sorts as year 70. Test: `tests/integration/track/recording/test_filters.py`.
- **Recordings**: `?from=<recording uuid>` looks the anchor up in one query, so an anchor removed mid-request gives a 404 instead of a 500.

## [12.9.0] - 2026-10-15

### Added

- **Recordings**: `library/recordings/?withTotal=false` skips the `COUNT(*)` and the `created_on` sort: pages are ordered by pk and `next` comes from fetching one extra row. `overallTotal` and `totalPages` are `null`. Without the param nothing changes. Lets the genre detail panel page huge subtrees without timing out. Test: `tests/integration/track/recording/test_list.py`.

### Fixed

- **Recordings**: `library/recordings/?genre=<uuid>` 500'd on large genres (gunicorn worker timeout): the genre-or-descendants `OR` with a subquery forced a seq scan over all recordings. Descendant ids are now materialized into a single `IN` list so the genre index is used. Test: `tests/integration/track/recording/test_list.py`.

## [12.8.0] - 2026-10-14

### Added

- **Recordings**: `library/recordings/?playable=true|false` (video set and not marked unplayable) and `?from=<recording uuid>` (start the list at that recording in the current ordering; 404 if not in the list, 400 if not a UUID).
- **Artists**: read-only `isSpecialPurpose` on the minimal artist payload, true for the 9 special-purpose MBIDs.

### Changed

- **Recordings**: `albumYear` ordering uses the new `first_release_year` (migration `0053`), falling back to a four-digit album year, so recordings without an album are ordered too. Covered by filter and serializer tests.

## [12.7.0] - 2026-10-14

### Added

- **Play from a track**: playlist `tracks/` endpoints (`genre-playlists/<uuid>/tracks/` and the other playlist routes) accept `?from=<track uuid>` and start the list at that track, in play order, so clients get it in one request instead of paging. A track not in the playlist gives a 404 and a non-UUID `from` gives a 400 (genre-kit v0.46.1, api-kit v0.10.2, which also turns any DRF `NotFound` into a 404 instead of a 500). Covered by a genre playlist tracks test.

## [12.6.0] - 2026-10-14

### Fixed

- **Artists**: `tracksCount` counts only recordings with a genre, matching `library/recordings/?artist=`; the detail keeps `createdOn` and `updatedOn`; imported release-group years must be four digits so album years sort chronologically. Covered by serializer and part-loader tests.
- **Songs merge**: a song without an artist MBID is no longer credited to a namesake artist that has one. Covered by a Postgres merge test.

### Documentation

- `docs/api/artists.md`: album `year` is a string, and `albumYear` ordering only applies to recordings with an album.

## [12.5.0] - 2026-10-14

### Added

- **Dev seed**: `docker compose up` on an empty DB now seeds it with the pinned `perf/fixtures/` Gold snapshot (genre trees and songs, through the nightly sync's import endpoints), so a fresh dev setup has a working genre tree without the multi-GB prod restore.
- **Recordings**: `library/recordings/` serves the track library (CRUD, `songs/import-runs/`, `songs/import/<taskId>/status/`). Track payloads gain a nested `youtubeVideo: {id, unplayableReason} | null`. Covered by list, playlist-page and legacy-route tests, plus a Postgres merge test for essential tracks.
- **Genre filter**: `library/recordings/?genre=<uuid>` lists a genre's recordings and those of its primary descendants, with or without a video. Covered by a filter test.
- **Artist page data**: artists gain MusicBrainz details (`musicbrainzArtistId`, `type`, `country`, `beginYear`, `endYear`, `ended`), group memberships (years, `ended`, roles), links and release-group albums (`primaryType`, `secondaryTypes`); `artists/{uuid}/` returns them with `memberOf` and `tracksCount` (see `docs/api/artists.md`). Migration `0052`. Covered by serializer, model and query-budget tests.
- **Artists import**: `artists/import-runs/` (create, gzip NDJSON parts, commit) and `artists/import/<taskId>/status/`, run by the nightly pipeline after songs: a Postgres merge upserts artists on MBID, replaces their memberships, links and release-group album credits, and deletes uncredited artists missing from the run. Covered by part-loader, protocol and Postgres merge tests.
- **Recordings filters**: `library/recordings/?artist=<uuid>` and `?ordering=title|-title|albumYear|-albumYear` (nulls last). Covered by filter tests.

### Changed

- **Bulk import runs**: `SongImportRun` becomes `BulkImportRun` (table `grow_bulk_import_run`) with a `kind`, so creating a run only abandons uncommitted runs of its kind.
- **Songs merge**: song artists are upserted on their MusicBrainz ID (adopting a legacy name-matched artist), and the merge no longer deletes orphan artists, the artists import owning their lifecycle. Covered by a Postgres merge test.
- **Artist payloads**: the artist list uses the simple serializer (`tracksCount`, no embedded tracks) and the detail no longer embeds tracks; fetch them with `library/recordings/?artist=<uuid>`.
- **Playable-only playlists**: genre playlists hold only playable recordings (YouTube video and no unplayable reason), via genre-kit v0.45.0's `_is_playable` hook and the bulk-import merge, which now adds or drops rels when playability changes and closes the position gaps. Migration `0051` drops existing unplayable rels and renumbers. Covered by manager, Postgres merge, migration and playlist-page tests.
- **Recording rename**: the `YoutubeTrack` model is now `Recording` (table `grow_recording`, migration `0050`; the essential-tracks join column becomes `recording_id`). The library list now includes recordings without a YouTube video; genreless ones stay hidden.
- A root genre may have at most one `side="pop"` direct child. Genre-kit v0.44.0 rejects a second one on save and on tree import (400, `REFERENCE_INVALID`), and the curation `canonical_genre_pop_side` list rejects a second pop child for the same root (400).

### Deprecated

- `library/youtube/` (alias of `library/recordings/` whose list still hides recordings without a video) and the flat `youtubeVideoId` / `youtubeUnplayableReason` track fields, superseded by `youtubeVideo`. Kept until consumers migrate.

## [12.4.0] - 2026-10-13

### Added

- Pipeline run requests now record their origin: `trigger` (`manual` or `scheduled`) and `requestedBy` (the requesting admin's email, or `null`). The pipeline API key can `POST pipeline/runs/` to queue the nightly `full` run as `scheduled` (`curation` returns 400); an admin's request is `manual`. Migration `0049` adds both fields, marking existing rows `manual` with no requester.
- `GET pipeline/runs/` lists past run requests, newest first, paginated (admin only).

## [12.3.0] - 2026-10-13

### Improved

- The cold (uncached) genre-tree response no longer spends ~3–4 s on Postgres JIT compilation: JIT is now off for the app's database connections.
- The cold genre tree is now built from plain `.values()` rows instead of hydrating ~1.7k model graphs through `CriteriaPlaylistSimpleSerializer`, with byte-identical JSON. Its track count uses genre-kit v0.43.2's index-only `Count("*")`. Local cold p50 went from ~3.1 s to ~1.2 s, so the perf SLO is tightened from 3000 ms to 2400 ms.

### Changed

- The shared filters and the criteria/playlist filtersets now come from api-kit v0.10.0 and genre-kit v0.43.0 instead of a local copy under `grow/filtering/`. Query params are unchanged.

### Added

- Genre playlist responses now include `criteria.wikidataId` (the root's QID or `LOCAL:` key) via genre-kit v0.41.0, so tree clients can key per-root colors on a stable id.

### Fixed

- The genre tree now follows genre moves made by the curation import. A playlist's `parent` and `root` are derived from its genre (genre-kit v0.42.0) instead of being stored in a second copy that the import's bulk writes skipped. Migration `0048` drops `grow_criteria_playlist.parent_id` and `root_id`. The response shape is unchanged.
- The manual-playlist and playlist `name` filters now match on the stored `_name` column (fixed in genre-kit v0.43.0).
- Invalid-UUID errors from the `parent` filter are reported under `parent` again instead of the internal ORM path (genre-kit v0.43.1, api-kit v0.10.1).

## [12.2.0] - 2026-10-12

### Added

- Pipeline runs on demand: `POST pipeline/runs/` with `{"kind": "curation"|"full"}` (admin) queues a request, either a rebuild of the canonical tree and songs from current curation or a full ingestion (the nightly run), returning 409 while any request is queued or running (one heavy run at a time) and 400 for a `curation` run with no edit pending. The pipeline's poller claims the oldest queued one with `POST pipeline/runs/claim/` (`running`, or for `curation` `superseded` when a nightly run already applied every edit; 204 when none), reports `stage`, `stageCurrent`/`stageTotal` and final `status` (`succeeded`/`failed`/`cancelled`, with `error`) on `PATCH pipeline/runs/<uuid>/`, where every call (an empty body included) is a heartbeat and the response's `cancelRequested` tells the poller to stop. `POST pipeline/runs/<uuid>/cancel/` (admin) cancels a queued request outright or flags a running one. A running request with no heartbeat for 30 minutes (`PIPELINE_RUN_HEARTBEAT_TIMEOUT_MINUTES`) becomes `expired`, checked on create, latest, claim, PATCH and cancel, so a dead run no longer blocks the queue. `GET pipeline/runs/latest/` returns the newest request (204 when none). New `PipelineRunRequest` model whose partial unique constraint allows one active request (migrations `0046`, `0047`). `curation/status/`'s `pendingCount` now comes from `CurationSyncState.pending_count`, shared with these endpoints. Covered by integration tests.

## [12.1.0] - 2026-10-09

### Changed

- Bumped `the-music-tree-genre-kit` to v0.40.0: drops the unused `(user, title)` index on tracks (`DROP INDEX CONCURRENTLY`, runs at container start). The longest stored title sat 3 bytes under the btree row limit, so a longer one would have failed the whole nightly songs merge. Deploy outside the nightly merge window, or the migration waits for the merge to finish.

### Improved

- The song import merge sets genre-playlist positions when it inserts rels instead of updating every new rel afterwards, so it no longer rewrites each new rel row or re-runs its foreign-key checks (about 25% faster on a re-import in a 100k-song benchmark).

## [12.0.0] - 2026-10-09

### Breaking

- `library/youtube/songs/import/` is removed. Songs now load through a staged import run: `POST library/youtube/songs/import-runs/` returns `{"runId"}` (and abandons any earlier uncommitted run), `PUT …/import-runs/<runId>/parts/<n>/` takes a gzip NDJSON body (`Content-Encoding: gzip`, `Content-Type: application/x-ndjson`, one snake_case song per line) and returns `{"count"}`, and `POST …/import-runs/<runId>/commit/` returns 202 `{"taskId"}`, polled at the unchanged `songs/import/<taskId>/status/`. Pipeline API key or admin only.

**Deploy note**: release together with the infrastructure songs sync switch to import runs and the-music-tree-pipelines chunked Gold song export: the nightly songs sync 404s against this release until it does.

### CI

- The Pytest job runs a Postgres 16 service and the `postgres`-marked tests (`pytest -m postgres --ds=tests.postgres_settings --no-cov`) next to the default SQLite run.
- Deploys: bumped `trigger-coolify-deploy` to v4.4.0 — a Coolify deployment stuck past an hour is cancelled (its build container force-stopped over SSH) instead of blocking every later deploy, and a failed or cancelled deploy posts an alert to the env's Discord status-alerts channel

### Changed

- Track titles and artist names accept up to 2048 characters (were 256), so real MusicBrainz songs (titles up to 1059, artist names up to 1018 characters) import instead of failing part validation. Bumps `the-music-tree-genre-kit` to v0.39.0 (widens the kit `Track.title`) and widens `Artist.name` (migration `0045`).
- `YoutubeTrack.youtube_video_id` is nullable (migration `0044`) so songs with no video are stored; songs with no genre are stored with a null genre and no playlist rels. `library/youtube/` lists only tracks with both a video and a genre.
- genre-kit bumped to `v0.38.0`, which drops the seed-song import now owned by grow.
- django-q2 task timeout raised to 4h (retry 15000s): a 1M-song merge commits in about 10 minutes on local Postgres, and a full sync carries about 10M songs.

### Added

- Staged bulk song import (`grow/track/bulk_import/`, migration `0044`): parts are streamed, gunzipped and loaded with Postgres `COPY` into the unlogged `grow_song_import_staging` table, and the commit task merges them in one transaction with set-based SQL: upserts artists, upserts tracks by `musicbrainz_recording_id` (adopting legacy rows by video id), keeps the genre of manually edited tracks, deletes stale unlocked tracks, rebuilds genre playlist rels for tracks whose genre changed, and records an `ImportRun` for pipeline commits. A commit with no staged songs fails instead of deleting the library, and a new run only abandons uncommitted runs, never one whose merge is still queued. Scales to millions of songs instead of one `save()` per row inside a request. Covered by Postgres-marked integration tests; the perf seed uses the new protocol.
- `YoutubeTrack.musicbrainz_recording_id` (migration `0043`): the MusicBrainz recording MBID, unique and nullable (hand-made tracks have none), returned as `musicbrainzRecordingId` on youtube track list and detail responses. Covered by integration tests.

### Fixed

- The songs merge inserts new tracks, YouTube tracks and track-artist rows in `track_id` order, so their primary key and `track_id` indexes fill sequentially instead of evicting a random index page per row. Profiling a 30.9M-song staging merge showed most of its time went to that eviction and WAL flushing.
- Request bodies up to 20 MiB are accepted (`DATA_UPLOAD_MAX_MEMORY_SIZE`). The pipeline's `library/youtube/songs/import/` payload grew past Django's 2.5 MiB default once it carried `musicbrainz_recording_id` (2.8 MB at 11,160 songs), and Django rejected it with a bare 400 before reaching the view, failing the daily staging sync.
- Curation writes are serialized with a Postgres advisory lock. Before, two concurrent rules (e.g. `a over b` and `b over a`) could each pass the cycle or list-exclusivity check without seeing the other and save an invalid state.
- Migration `0035` seeds from a frozen JSON snapshot instead of the current registry and seed CSVs, so later list changes can no longer break migrating a fresh database.

## [11.4.0] - 2026-10-07

### Added

- `genre_precedence` curation list (source `musicbrainz`, consumed by the pipeline's musicbrainz Silver `5_songs`): `(musicbrainz_genre_name, over_musicbrainz_genre_name, reason)`, the first, more precise MusicBrainz genre winning over the second on a recording carrying both. Both names must be lowercase, free of leading or trailing whitespace, and differ, and a rule closing a precedence cycle (reversing an existing rule, or a longer chain such as a over b, b over c, c over a) is rejected with a 400 naming the cycle, on create, patch and CSV import alike, since either fails the pipeline's daily run. Migration `0042` seeds 50 rules (e.g. ska over reggae, pop rock over pop) on existing databases too, inlined so it doesn't break if the list is later renamed or its seed CSV removed. Covered by integration tests.

## [11.3.0] - 2026-10-06

### Added

- Pipeline import history for the admin freshness page (`ImportRun`, migration `0041`): every `X-API-Key` canonical/regional `genres/tree/import/` (node count, written in the import's transaction so a failed import records nothing) and `library/youtube/songs/import/` (imported and skipped counts, written by the async task) records a run; admin imports don't. `POST pipeline/imports/unresolved-genre-tags/` (pipeline key or admin) records the pipeline's unresolved genre tag count. `GET pipeline/imports/latest/` (newest run per kind) and `GET pipeline/imports/?kind=` (paginated, newest first) are admin only. Covered by integration tests.
- `isUnacceptedRoot` on every criteria playlist output (`genre-playlists/tree/` and the genre/tag/criteria playlist lists): `true` only for a genre playlist whose genre is an import-created root still awaiting admin acceptance, `false` for everything else (accepted genres, tags, Genreless/Tagless); only the root itself is flagged, so consumers hide its subtree via each row's `root`. Accepting a root already bumps the tree cache token. Covered by integration tests.

## [11.2.0] - 2026-10-04

### Added

- `YoutubeTrack.youtube_unplayable_reason` (nullable; `not_found`, `not_embeddable`, `private`, `not_processed`, `region_whitelisted`; migration `0040`), set by the pipeline songs import from each entry's `youtubeUnplayableReason` (an omitted key clears the flag) and returned as `youtubeUnplayableReason` on every YouTube track output (`null` = playable), so the frontend can grey out videos YouTube won't play. Genre-kit 0.35.2 → 0.36.0. Covered by integration tests.

## [11.1.0] - 2026-10-03

### Added

- `GET genre-playlists/tree/?treeName=`: the whole canonical or regional genre tree in one unpaginated response, cached in Redis for 7 days (new `CACHES` setting, needs `REDIS_URL`) and keyed on a version token that Postgres statement-level triggers regenerate on every write to a table the tree serializes (`GenreTreeVersion` singleton, migration `0039`). Recording a play no longer bumps `updated_on` (it increments `play_count` with a queryset update) so plays don't invalidate the tree; the playlist table's trigger only fires on updates to columns the tree reads. The cache key and `ETag` include `GIT_COMMIT`, and an unreachable Redis is logged and bypassed rather than failing the request. Responses carry an `ETag`, and `If-None-Match` returns 304. Covered by integration tests, query budgets (cold 4, warm 1, not-modified 1) and latency SLOs.
- `GET curation/status/` (admin): `appliedExportOn` (the pipeline export the canonical tree was last built from) and `pendingCount` (canonical curation entries created, edited or deleted since). The pipeline's `curation/export/` records its time and its canonical `genres/tree/import/` marks that export applied (new `CurationSyncState` singleton, migration `0038`). Covered by integration tests.
- `GET curation/history/` (admin): canonical curation edits newest first, filterable by `list`, `entry` uuid or `item_id`, each with its entry uuid and the editor pseudo (`null` for the pipeline). Curation history snapshots now carry `list_name`; migration `0037` backfills it for entries still alive. Covered by integration tests.
- Curation API, for the admin editor: `GET curation/lists/` returns each list's entry `count`; `GET curation/<list>/entries/` accepts `?q=` (case-insensitive match on key, values, reason, or the name of the canonical genre whose QID is the key) and `?ordering=key|-updated_on` (most recently edited or created first), and returns a `labels` map (QID → canonical genre name) for every item-id column on the page. Covered by integration tests.
- `GET curation/rules/?item_id=`: every canonical curation entry referencing an item, across lists (as the key, as part of a composite key, or as an item-id value), with the same `labels` map. Genres now expose `wikidataId` and accept a `?wikidata_id=` filter. Covered by integration tests.

### Fixed

- `scripts/restore-prod-db.sh` drops and recreates the local `public` schema before `pg_restore`. It reads the whole dump first, so a corrupt download fails before the local database is wiped. Tables created by local migrations that prod hasn't run yet were surviving the restore, so `migrate` then failed with `relation … already exists`.
- Stable pagination order for list endpoints: rows sharing `created_on` no longer repeat or vanish across pages (genre-kit 0.35.2 → api-kit 0.9.1 adds a `pk` tie-breaker to the default ordering; the playlist name/type filter does the same).

## [11.0.0] - 2026-10-01

### Added

- Curation domain: the pipelines' 18 hand-edited `manual_*.csv` lists now live in the API as `CurationEntry` rows (registry in `grow/curation/lists.py`). Admin CRUD on `curation/{list}/entries/`, `curation/lists/`, and `curation/export/` (pipeline key or admin) returning every list as CSV-ready rows. Rows are validated (columns, QIDs, booleans, unique key, mutual exclusivity of theme/technique/out-of-scope/duplicate lists) and every write records a `HistoryEntry` (new `updated` action). Migration `0035` seeds from the vendored CSVs when the table is empty; `manage.py import_curation_csvs <dir>` upserts from a directory. Tests cover auth, CRUD, validation, history, export shape and the seed round trip.
- Admin edits of wikidata-backed genres now also upsert a curation rule keyed by the genre's `wikidataId`, so the pipeline reproduces them instead of only skipping the locked row: rename → `label_overrides`, canonical reparent → `main_parent` (`exclude_other_parents`), root acceptance → `accepted_canonical_roots`, exclusion → `<category>_genres`, each with reason `grow admin edit by <pseudo>` and through the same validation as the curation API. Reparents no list expresses (to a root, under an app-created genre, or in the regional tree) return 400. App-created genres (no `wikidataId`) and synthetic `LOCAL:` genres keep lock-only edits. Migration `0036` converts existing locked or excluded genres into rules from their admin history trail (exclusions, whose category was never recorded, go to `out_of_scope_genres`); locks stay. Tests cover each mapping, the 400s, and the migration's idempotence.

### Changed

- **Breaking**: reparenting a wikidata genre to a root, under an app-created genre, from or to an excluded genre, or anywhere in the regional tree now returns 400 instead of succeeding, since no curation rule can express it.
- **Breaking**: excluding a wikidata genre that a `main_parent` or `regional_overrides` rule moves, or moves another item under, now returns 400 naming that rule.
- **Breaking**: `POST genres/{uuid}/exclude/` requires `{"category": "theme"|"technique"|"out_of_scope"|"duplicate"}`; a missing or unknown category returns 400.

### Fixed

- Docker builds pin `ghcr.io/astral-sh/uv` to `0.11` instead of `latest`: the 2026-09-29 amd64 `latest` image ships a non-executable `/uv`, so `uv sync` failed with `Exec format error`.
- `curation/` `POST`/`PATCH` with a non-object JSON body return 400 instead of 500.
- Curation item ids are matched in full (`re.fullmatch`, ASCII `[0-9]`): a trailing newline or non-ASCII digits are rejected.
- A curation key longer than 512 characters returns 400 instead of a database error.
- `import_curation_csvs` updates now record an `updated` history entry and touch `updated_on`; unchanged rows are skipped and counted (`N created, N updated, N unchanged`).

## [10.0.0] - 2026-09-30

### Changed

- **Breaking**: a genre's tree is now named by `treeName` (`canonical` or `regional`) instead of the `allowsMultiplePrimaryParents` flag. Tree import payloads must carry `treeName`; `GET {genres|tags}/tree/` requires `?treeName=`; `genre-playlists/` filters with `?treeName=` (`canonical` keeps the Genreless playlist) instead of `?allows_multiple_primary_parents=`. Unknown values return 400. Migration `0033` maps `allows_multiple_primary_parents=True` to `regional`. Perf fixtures refreshed to the new payload shape. Bumps genre-kit to v0.35.1 (api-kit v0.9.0). Tests cover the migration, both filters, and the 400s.
- **Breaking**: `genres/` `?hasNameConflict=` and `?isUnacceptedRoot=` accept only `true`/`false`/`1`/`0`; anything else returns 400 `invalid_filter` instead of being ignored.
- **Breaking**: history responses (`GET {genres|youtube-tracks}/{uuid}/history/`) drop `actorEmail` for `actorPseudo` (the admin's public pseudo, `null` for pipeline changes) and are now ordered newest first. `HistoryEntry.actor_email` becomes an `actor` FK to `User`; migration `0032` maps existing emails to their `User` and fails if any email has no match. Tests cover the payload, ordering, the migration mapping and the new command.

### Added

- `UserProfile` model (`pseudo`, unique) and the `set_user_pseudo <email> <pseudo>` management command (refuses a pseudo already taken).

**Deploy note**: merge and deploy together with the-music-tree-pipelines PR #131 (gold exports `treeName`): the nightly tree import 400s against this release until it does.

**Deploy note**: after migrating, run `manage.py set_user_pseudo <admin-email> <pseudo>` for every admin with history entries. Until then, history endpoints listing their entries return 500.

## [9.0.0] - 2026-09-30

### Changed

- The Docker image is now a multi-stage build on `python:3.14-slim-bookworm`: 244 MB on disk instead of 1.17 GB. It keeps `curl`, which Coolify's own healthcheck runs inside the container. uv and git stay in the `builder` stage, which `docker-compose.override.yml` now targets for local dev. Added a `.dockerignore`.

### Removed

- **Breaking**: playlist detail responses (`GET {playlists|genre-playlists|tag-playlists|manual-playlists}/{uuid}/`) no longer include `trackPlaylistRelations`; read tracks from the paged `{uuid}/tracks/` endpoint. The largest genre's detail drops from ~5 s to tens of ms (2 queries); detail query budgets and latency SLOs tightened accordingly. The `youtubeVideoId` regression test now covers the tracks endpoint.

### Added

- `genre-playlists/` list accepts `?allows_multiple_primary_parents=` to pick one genre tree. `false` returns only the canonical tree. Without it, the regional tree's ~630 genres that have no regional parent show up as extra roots. Test included.
- Bruno `genre-playlist-tracks` request.
- GET responses now carry an `ETag` and answer a matching `If-None-Match` with `304 Not Modified` (Django `ConditionalGetMiddleware`), so clients revalidating the genre tree skip re-downloading it. The query and serialization still run; only the transfer is saved.

## [8.3.3] - 2026-09-29

### Fixed

- **`/health/` `commit` on image-based deploys**: Coolify sets `SOURCE_COMMIT=HEAD` at runtime for apps deployed from a registry image, so `commit` reported `HEAD`. The build workflow now bakes the commit SHA into the image as `GIT_COMMIT` (Dockerfile build arg), which the settings read instead of `SOURCE_COMMIT`.
- **Build tag races**: `build-and-deploy.yml` now serializes runs per branch (workflow-level concurrency), so a slower older build can no longer overwrite a newer `:staging`/`:prod` tag.

## [8.3.2] - 2026-09-29

### Added

- Manual `workflow_dispatch` trigger on `build-and-deploy.yml`, to rebuild and redeploy a branch's image when a push run didn't fire.

## [8.3.1] - 2026-09-28

### Added

- `build-and-deploy.yml` workflow: on push to `develop`/`main`, builds the Docker image on GitHub-hosted runners and pushes it to GHCR (`ghcr.io/behindthemusictree/gtmt-api`, tags `staging`/`prod` plus `sha-<short>`), then triggers the Coolify deploys of `gtmt-api` and its `worker`, moving image builds off the VPS.
- `scripts/restore-prod-db.sh`: restore the latest prod backup from R2 into the local Docker Compose DB.

## [8.3.0] - 2026-09-28

### Added

- Unaccepted root genres: the tree import copies each node's optional `isUnacceptedRoot` onto the genre (recomputed for unlocked rows), so the pipeline can emit a canonical root it hasn't accepted instead of failing. `GET /v1/genres/unaccepted-roots/` lists them (uuid, name, `wikidataId`, …, ordered by name); `POST /v1/genres/unaccepted-roots/accept/` (`{"genres": [{"uuid": ...}]}`, admin only, 204) unflags and locks them and records a `root_accepted` history entry. An admin reparent also clears the flag. Genres expose `isUnacceptedRoot` and filter on `?is_unaccepted_root=`. Tests included.

### Changed

- Upgraded `the-music-tree-genre-kit` to v0.34.0 (adds `Genre.is_unaccepted_root`, migration `0030_genre_is_unaccepted_root`).

## [8.2.0] - 2026-09-27

### Added

- `GET /v1/{playlists,genre-playlists,tag-playlists,manual-playlists}/{uuid}/tracks/`: a paginated, position-ordered page of a playlist's tracks, without each track's nested `playlists`. The largest genre's first 100 tracks load in about 60 ms, against about 4.5 s for the full detail. Query budget and latency SLO included.

### Changed

- Upgraded `the-music-tree-genre-kit` to v0.33.0: a playlist can no longer hold the same track twice, and positions stay unique across song re-imports. Its migration deletes duplicate playlist-track rows (keeping the lowest position) and renumbers positions 1..n per playlist; it cannot be reversed.
- Playlist detail `tracksCount` now counts distinct tracks, like the lists.
- `/v1/plays/` (list, retrieve and create) returns `content` at minimum depth (uuid plus name or title) instead of the full playlist or track, and the list runs a fixed number of queries. No client reads plays' nested content.
- Tests now run with the production camelCase parser and renderer, so they exercise the real wire format.

## [8.1.0] - 2026-09-27

### Added

- Performance gates. Query budgets per endpoint run in `pytest`. Latency SLOs run in the new CI job `Perf`, on Postgres, seeded from a pinned snapshot of the prod pipeline's Gold exports. See README "Performance".

### Changed

- Upgraded `the-music-tree-genre-kit` to v0.32.1, and `the-music-tree-api-kit` to v0.8.0 through it.

### Fixed

- `GET /v1/playlists/`, `GET /v1/genres/`, and the playlist and genre-playlist detail endpoints ran queries per row or per track. Each serializer now declares what it loads, so every endpoint runs a fixed number of queries. The largest genre's detail went from 9,000 queries and about 165 s to 6 queries and about 5 s. The playlist list went from 503 queries and 2.6 s to 2 queries and 47 ms.

## [8.0.0] - 2026-09-27

### Added

- `GET /v1/genres/{uuid}/overview/` (and `/v1/tags/{uuid}/overview/`): a lean criteria payload with only `uuid`, `name`, `summary`, `side` and `essentialTracks`, for views that don't need the full detail response (tracks, lineage, children, playlist). It runs a fixed number of queries however many essential tracks the genre has; tests guard the field set, the 404 and the query count.

### Changed

- Upgraded `the-music-tree-genre-kit` to v0.31.0. Track archiving now belongs to hear only, and the kit migration drops the unused `archived` column from the shared track table. Every grow track had `archived = false`.

### Removed

- `tracksArchivedCount` from the artist, album, playlist, genre-playlist and genre detail responses, and `archived` from YouTube track responses.

### Fixed

- `GET /v1/genre-playlists/` ran several queries per row, so large pages timed out behind the proxy with a 502. The list now runs a fixed number of queries whatever the page size, and a query-count test guards against regressions.

## [7.2.0] - 2026-09-26

### Added

- Genre name conflicts can now be reviewed as groups. `GET /v1/genres/name-conflicts/` groups each flagged genre with the genres that share its base name. With `POST /v1/genres/name-conflicts/validate/`, an admin saves the group's final names in one step: unchanged flagged genres are marked as reviewed and locked, and a clashing name returns a 400 on that genre's uuid, with nothing saved.

## [7.1.0] - 2026-09-26

### Added

- Genre name conflicts no longer fail the tree import. When a genre's name is already taken, case-insensitively, by a genre with a different Wikidata ID, it is imported as `"<name> (<wikidata_id>)"` and flagged with `hasNameConflict`. The new `GET /v1/genres/?hasNameConflict=true` filter lists these genres for admin review. An admin rename clears the flag and locks the name against later imports. Upgraded `the-music-tree-genre-kit` to v0.30.0.

## [7.0.0] - 2026-09-26

### Changed

- **Breaking:** upgraded `the-music-tree-genre-kit` from v0.27.0 to v0.29.0 (multi-parent criteria).
  - `GET /v1/{genres,tags}/tree/` now requires the `allowsMultiplePrimaryParents` query param; omitting it returns 400.
  - Tree import payloads must carry `allowsMultiplePrimaryParents`, and every genre node must have a Wikidata `id` (`Q<n>`).
  - Tree output now includes `allowsMultiplePrimaryParents`, `primaryParents`, and `secondaryParents`.
  - A tree import only deletes pipeline-sourced, non-manually-edited genres. It is refused (400) when it would delete
    more than `CRITERIA_TREE_IMPORT_STALE_DELETE_MAX_FRACTION` (0.5) of them.
- Criteria names are now unique case-insensitively.
  - Migration `0025` adds the multi-parent fields plus genre `source`/`last_seen_run`.
  - Migration `0026` backfills `source`: `admin` for manually edited rows, `pipeline` for other ownerless or
    Wikidata-backed rows. Legacy ownerless genres imported without an id (NULL `wikidata_id`) are kept; genre-kit
    0.29.1's import adopts them by name and sets their `wikidata_id`.
  - Migration `0027` adds the constraints and fails on any remaining conflict. No DB constraint on genre
    `wikidata_id`: `user` lives on the parent `Criteria` table (MTI, `models.E016`), which crashed the staging
    `migrate`; the keyed import matches by `wikidata_id` instead. A test now runs the database system checks.
  - Covered by tree, import, and migration tests.
- Bumped `the-music-tree-genre-kit` to v0.29.3: the songs import batches playlist moves for re-genred tracks
  instead of shifting positions one track at a time (staging import timed out at the 1800s django-q limit).
- Bumped `the-music-tree-genre-kit` to v0.29.4: the tree import rebuilds genre lineage in one batch instead of
  per-row queries (staging's canonical tree import took >120s and hit the gunicorn timeout; now ~13s).

## [6.0.0] - 2026-09-25

### Added

- Admin edits to genres and songs now win over the next pipeline sync: an admin rename, reparent, or
  re-tag locks that field against the daily rebuild, and `POST /v1/genres/{id}/exclude/` soft-removes
  a Wikidata-backed genre without it reappearing on the next import.
- `GET /v1/genres/{id}/history/` and `GET /v1/library/youtube/songs/{id}/history/` return each
  genre's/song's actor+timestamp+action edit history.

### Changed

- Reference data no longer belongs to a "system user": genres, tags, playlists, tracks, artists, albums, plays,
  and history rows are now canonical rows with no owner (`user IS NULL`), readable by everyone. Migration
  `0024_ownerless_reference_data` moves the system user's rows to `user IS NULL` and deletes the system user.
  Criteria names are unique among canonical rows, and per user among personal rows. Covered by new permission,
  ownership, and migration tests.
- Google sign-in now resolves to a real `User` keyed by the account's `sub` (created on first sign-in); the
  pipeline API key resolves to a row-less service principal. Neither owns reference data.
- The default DRF permission is now `IsAdminOrReadOnly` instead of `IsAuthenticated`.
- Bumped `the-music-tree-genre-kit` pin to `v0.26.0` (nullable `user` on `Track`/`Playlist`/`TrackPlaylistRel`,
  and `the-music-tree-api-kit` `v0.7.0`'s `get_owner` hook).

### Removed

- `SYSTEM_USERNAME` setting and environment variable, `get_system_user`, and the `post_save` signal that
  bootstrapped criteria-less playlists per user.
- `POST /v1/genres/tree/load-seed/` and `POST /v1/library/youtube/songs/load-seed/`, the bundled
  `grow/data/seed_genre_tree.json` fixture, and the `DATA_DIR` setting. Genre data now comes only from the
  pipeline import (`tree/import/`, `songs/import/`) and admin edits. Bumped `the-music-tree-genre-kit` pin to
  `v0.27.0`, which drops the seed mixins. Load-seed tests removed.

## [5.0.0] - 2026-09-24

### Removed

- **BREAKING:** the deprecated `/v0/` URL namespace and its `Deprecation`/`Sunset` headers middleware
  are removed. All endpoints are served under `/v1/` only; `/v0/` requests now return 404.

## [4.0.0] - 2026-09-24

### Changed

- **BREAKING:** the API key env var is renamed from `GROW_API_KEY` to `PIPELINE_API_KEY`. The key
  now only authorizes the pipeline import endpoints, and the pipelines are its only consumer. There
  is no fallback to the old name: deployments must set `PIPELINE_API_KEY` before upgrading.

## [3.0.0] - 2026-09-24

### Added

- **Google sign-in for the admin**: requests can authenticate with `Authorization: Bearer <Google ID token>`, verified against `GOOGLE_OAUTH_CLIENT_ID`. The account whose `sub` matches `ADMIN_GOOGLE_SUB` gets the `admin` role and can write; any other verified Google account is a read-only `viewer` (writes return 403 `permission_denied`). Invalid or expired tokens return 401 `invalid_token`. Google's signing certs are cached per their `Cache-Control` max-age, and if Google can't be reached, the request returns 503 `auth_provider_unavailable` instead of a 500. Both env vars are required.
- `GET /v1/auth/me/` returns the caller's `{"role", "email"}`, or 401 `authentication_required` when anonymous.
- **Stable `v1` URL namespace**: the API is served under `/v1/`, a fixed constant instead of the major of `APP_VERSION`, so a release version bump no longer changes every URL. `/health/` now reports `version` from `pyproject.toml` and `commit` from the `SOURCE_COMMIT` env var Coolify injects at runtime.

### Changed

- The `X-API-Key` now authenticates as the `pipeline` role and can only write to the nightly pipeline's import endpoints (`genres/tree/import/`, `library/youtube/songs/import/`); any other write with the key returns 403 `permission_denied`. The admin's Google token can still call the imports too. The key is now compared in constant time.

### Deprecated

- `/v0/` stays as an alias of `/v1/` until it's removed; its responses carry `Deprecation` (RFC 9745) and `Sunset: Thu, 24 Dec 2026 00:00:00 GMT` (RFC 8594) headers.

### Removed

- The `APP_VERSION` env var and Docker build arg; the version is read from `pyproject.toml`.

## [2.0.1] - 2026-09-23

### Fixed

- **The django-q2 worker could never pass a deploy**: it reuses this image with `qcluster` as its process, but the image's `HEALTHCHECK` only probed the API's `/health/` endpoint, which the worker doesn't serve. Coolify waits on a Dockerfile `HEALTHCHECK` even when its own healthcheck is disabled, so every worker deploy would have failed. The healthcheck now passes while `qcluster` is running and still probes `/health/` in the API container.

## [2.0.0] - 2026-09-23

### Added

- Local knowledge-graph tooling (`graphify`) wired up for this repo, with a post-commit hook to keep the graph current. Output is gitignored, dev-only. Claude Code is now instructed (CLAUDE.md + `.claude/settings.json` hooks) to query the graph before raw file searches.
- `GET songs/import/<task_id>/status/` endpoint to poll the status of an in-progress song import (`pending`/`success`/`failed`).

### Changed

- `CONTRIBUTING.md`/`CLAUDE.md` branch-prefix conventions aligned to canonical Gitflow (`feature/`, `release/`, `hotfix/` only), dropping the non-standard `fix/`/`chore/` prefixes.
- **Breaking:** `POST songs/import/` now enqueues the import as a background task and returns `202 Accepted` with `{"task_id": ...}` instead of blocking until the import completes and returning `201`. Callers must poll the new status endpoint for completion. Requires a `REDIS_URL` env var (django-q2's Redis broker) in every environment running this app.

### Fixed

- `CONTRIBUTING.md`/`CLAUDE.md` referenced a nonexistent `.github/workflows/test.yml` as the CI workflow — the actual file is `validate.yml`.
- Bumped `the-music-tree-genre-kit` to `v0.23.4`, which batches `import_seed_songs`'s per-song
  artist M2M writes into a single `bulk_create`. Reduces one of the O(n) costs pushing
  `/songs/import` toward the gunicorn/Cloudflare request timeout on large imports.

## [1.2.0] - 2026-09-22

### Fixed

- **`genre-tree/import/` 500s on a partial reimport that adds a new node under an already-existing root**: staging's daily gold-export sync hit this via `grow-the-music-tree-pipelines`' `sync_to_grow` step. Fixed at the source by bumping `the-music-tree-genre-kit` to `v0.23.3`, which falls back to a DB lookup for a new criteria's parent/root when it predates the current reimport batch instead of assuming it's always present, raising `KeyError`.

### Added

- `Genre` gained a nullable `wikidata_id` field (Wikidata QID, e.g. `"Q9778"`), added via `grow/migrations/0020_genre_wikidata_id.py`.

### Fixed

- **Staging deploys of `develop` crash-looped since `wikidata_id` landed**: `Genre.Meta` carried a `unique_wikidata_id_per_user` constraint over `(wikidata_id, user)`, but `user` lives on the parent `Criteria` table (multi-table inheritance), not on `Genre`'s own table — Django's `models.E016` check rejects a constraint over a non-local field. `manage.py check`/`pytest` never run with `--database`, so CI never caught it; `manage.py migrate` does, so every deploy since (both attempts, `2026-09-18` and this session's) failed its healthcheck and rolled back, leaving staging on stale code. Per-user uniqueness on `wikidata_id` is still enforced in practice by `import_criteria_tree`'s `filter(user=user, wikidata_id__in=...)` match-by-QID query; dropped the unenforceable DB constraint (and the now-dead `AddConstraint` op in `0020_genre_wikidata_id.py`, which had never successfully applied anywhere) rather than working around Django's MTI restriction.

### Fixed

- **`genre-list/tree/import/` 500s when re-importing over genres still referenced by tracks**: `GenreViewSet.import_tree` deletes genres dropped from the incoming tree, but `YoutubeTrack.genre` is `on_delete=DO_NOTHING`, so re-importing after any earlier `tree/import/` or song import that left tracks pointing at a now-removed genre raised an unhandled `IntegrityError` (surfaced as a generic 500). Fixed at the source by bumping `the-music-tree-genre-kit` to `v0.23.2` (see below), which reparents affected tracks instead of raw-bulk-deleting the stale genre row out from under them; `import_tree`/`load_seed_tree` no longer need to pre-clear the requesting user's tracks as a workaround. Renamed `test_import_deletes_genre_still_referenced_by_a_track` to `test_import_reparents_track_off_a_genre_deleted_by_the_reimport` (`tests/integration/criteria/tree/import/test_overwrite.py`) to match the corrected behavior.

### Changed

- Bumped `the-music-tree-genre-kit` to `v0.23.2`: `import_criteria_tree`'s stale-genre deletions now reparent affected tracks (up to the nearest surviving ancestor, or null for a deleted root) instead of raw-bulk-deleting rows a track may still reference.
- Bumped `the-music-tree-genre-kit` to `v0.23.1`: tree-import nodes may now carry an optional `id` (Wikidata QID); `import_criteria_tree` matches incoming nodes against existing rows by `wikidataId` instead of always deleting and recreating the whole tree. Existing genres with no `wikidataId` are never touched by import/load-seed. `v0.23.1` fixes the idempotency gap in `v0.23.0` where id-less nodes were always recreated instead of matched, and the `IntegrityError` handling that only matched Postgres-formatted error text.
- `scripts/start-server.sh` now starts Gunicorn with `--timeout 120` and `--workers 2` (both overridable via `GUNICORN_TIMEOUT`/`GUNICORN_WORKERS`), replacing the implicit 30s timeout/1 worker defaults that were killing requests behind large imports.
- Bumped `the-music-tree-genre-kit` to `v0.19.0`, which batches `import_criteria_tree`'s ascendant `CriteriaLineageRel` inserts into a single `bulk_create` call instead of one per ancestor per node — no API changes affecting `grow`.
- Bumped `the-music-tree-genre-kit` to `v0.20.0`: `CriteriaManager` now overrides the kit's `_on_bulk_created` hook to call `CriteriaPlaylist.objects.bulk_create_for_criteria(instances)`, bulk-creating one `CriteriaPlaylist` row per criteria node after `import_criteria_tree`'s bulk insert instead of one `.create()` per node.
- Bumped `the-music-tree-genre-kit` to `v0.21.0`, which fixes the tree-import gunicorn worker timeout on deep genre trees: tree-node validation no longer re-validates every descendant subtree once per ancestor level (cost compounded with tree depth, not just node count), and `bulk_create_mti`'s raw insert now issues real multi-row `INSERT` statements instead of one round-trip per row — no API changes affecting `grow`.

### Removed

- Removed the prototype user entirely: `ReadOnlyForPrototypeUser` permission class, `get_prototype_user` helper, and the `seed_prototype_tree` management command are gone; `ApiKeyAuthentication` now only resolves `GROW_API_KEY` to the system user (its `GROW_PROTOTYPE_API_KEY` branch is removed); `GrowModelViewSet.permission_classes` is now just `[AuthenticatedForWritesReturn401]`. `grow/settings.py` no longer requires `PROTOTYPE_USERNAME`/`GROW_PROTOTYPE_API_KEY`. Added `grow/migrations/0019_delete_prototype_user.py`, which deletes the `prototype` user row (cascading via FKs); `grow/migrations/0013_create_prototype_user.py` no longer hard-fails when `PROTOTYPE_USERNAME` is unset, defaulting to `"prototype"` instead, since the row it creates is now immediately removed by `0019` on a fresh database and the env var is no longer required anywhere else.

### Changed

- The required "Mainstream Pop" root genre invariant (see below) now also guards direct `DELETE`/`PUT` on the root via normal Genre CRUD, not just `tree/import`/`tree/load-seed`: deleting the root, renaming it away, or reparenting it out from under `parent=None` now fails with a `dependency_missing` field error and rolls back. `GenreManager.REQUIRED_ROOT_GENRE_NAMES` generalizes the single hardcoded name into a set, the extension point for any future required root label (see `ARCHITECTURE.md`).
- Bumped `the-music-tree-genre-kit` to `v0.18.0`, which renames its example-data mixins/routes/fields to "seed" terminology: `GenreExampleTreeMixin`→`GenreSeedTreeMixin`, `SongExampleTreeMixin`→`SongSeedTreeMixin`, `tree/load-example`→`tree/load-seed`, `songs/load-example`→`songs/load-seed`, `import_example_songs`→`import_seed_songs`, `SongExampleFields`→`SongSeedFields`, `SongExampleImportSerializer`→`SongSeedImportSerializer`. Updated all usages in `grow` accordingly (`GenreViewSet`, `YoutubeTrackViewSet`).
- Renamed this repo's own analogous "example" identifiers to match: `GenreViewSet.load_example_tree`→`load_seed_tree`, `on_example_tree_loaded`→`on_seed_tree_loaded`, `example_songs_filename`→`seed_songs_filename`. Renamed the reusable fixture `grow/data/prototype_genre_tree.json`→`grow/data/seed_genre_tree.json`.

### Fixed

- `summary` is now surfaced in `CriteriaDetailedSerializer` output (the `genre-detail`/`tag-detail` endpoints), matching its existing presence in `CriteriaSimpleSerializer`. It had been added to the list serializer alongside the `summary` field itself but never added to the detail serializer's field list.

### Added

- **Dev tooling**: Added a `launch` Claude Code skill (`.claude/skills/launch/`) documenting how to start the app locally via Docker Compose.
- Genre tree writes (`tree/import`, `tree/load-seed`) now require a root genre named "Mainstream Pop"; a missing one fails the request with a `dependency_missing` field error and rolls back the whole write.
- Bumped `the-music-tree-genre-kit` to `v0.17.0`, which removes the constraint that at most one direct child of a root genre criteria may have `side="pop"` — a root may now have zero, one, or several pop children, needed for the pipelines Gold layer's canonical genre tree export to import cleanly.
- Bumped `the-music-tree-genre-kit` to `v0.16.0`, which adds `SongsImportMixin`. `YoutubeTrackViewSet` now mixes it in alongside the existing `SongExampleTreeMixin`, exposing a new `songs/import` (POST) action that accepts an arbitrary flat list of `{"title", "artist", "youtube_video_id", "genre_name"}` entries and replaces the current user's tracks — unlike `songs/load-example`, the payload comes from the request body rather than a bundled fixture file, so any external system (e.g. the pipelines Gold layer) can push a songs list directly.
- Bumped `the-music-tree-genre-kit` to `v0.15.0`, which adds an optional `summary` `TextField` (`null=True, blank=True`) to `AbstractCriteria`, shared by both `Genre` and `Tag` — a short standalone blurb for hover/card UI, distinct from any future detailed-genre-page content. Generated `grow/migrations/0017_criteria_summary.py`. `summary` is now surfaced in `CriteriaSimpleSerializer` output (the `genre-list`/`tag-list`/`genre-playlists`/`tag-playlists` endpoints) automatically via the kit's `build_criteria_simple_serializer`, and mirrored into `grow`'s local `CriteriaOutputFieldKey` enum.
- `Genre.essential_tracks`, a `grow`-local `ManyToManyField` to the track model letting each genre curate its own list of representative tracks, independently of any subgenre's list and independently of `Track.genre` (a track need not be tagged with the genre to be marked essential for it). Generated `grow/migrations/0018_genre_essential_tracks.py`. Surfaced as `essential_tracks` in `CriteriaDetailedSerializer` output via a new `CriteriaEssentialTracksSerializerMixin` (`grow/serializer/model/criteria/output/essential_tracks.py`, resolving to `[]` for non-`Genre` criteria like `Tag`), mirroring the kit's existing `CriteriaSideSerializerMixin` pattern.
- Write support for `essential_tracks` on `genre-list` (POST) and `genre-detail` (PUT), via new `GenrePostSerializer`/`GenrePutSerializer` (`grow/serializer/model/criteria/children/genre/input/`) declaring `essential_tracks` as an unscoped `PrimaryKeyRelatedField(queryset=YoutubeTrack.objects.all(), many=True)`, consistent with the single-tenant architecture. `CriteriaViewSet.__init__` now accepts overridable `create_serializer_class`/`update_serializer_class` params so `GenreViewSet` can inject the Genre-specific serializers while `TagViewSet` keeps the shared `CriteriaPostSerializer`/`CriteriaPutSerializer`. `GenreManager.create()` pops `essential_tracks` before calling `super().create()` (Django's base `create()` can't accept M2M kwargs before the instance has a PK) and applies `.set()` after, wrapped in `@transaction.atomic`; PUT already worked for free via the kit's `BaseManager.update_instance`, which generically applies M2M `.set()` after saving regular fields.

### Changed

- Renamed the `test.yml` GitHub Actions workflow to `validate.yml`.
- Configured the validation workflow to run on pushes to `main` and `develop`, in addition to pull requests targeting these branches.
- Bumped `the-music-tree-genre-kit` to `v0.13.0`. `AbstractCriteria.save()` now rejects setting `side` (`core`/`pop`) on a non-genre criteria, raising `AppValidationException(field_name="side", field_validation_error_code=FieldValidationErrorCode.DEPENDENCY_MISSING)` — previously a `Tag` could silently get a `side` with no error. Added a regression test (`tests/unit/model/criteria/test_criteria.py`) covering this for `Tag`. The kit also switched the `side` model field from `models.CharField` to `the-music-tree-api-kit`'s `AppCharField` (no DRF serializer behavior change, `choices` always forces `ChoiceField`); generated the corresponding `grow/migrations/0015_alter_criteria_side.py`.
- Bumped `the-music-tree-genre-kit` to `v0.14.1`. `CriteriaSimpleSerializer` and `CriteriaDetailedSerializer` now resolve `side` via the kit's `CriteriaSideSerializerMixin` (`the_music_tree_genre_kit.serializer.model.criteria.output.side`) instead of each hand-rolling its own `get_side()` — the kit's `build_criteria_simple_serializer` also mixes this in automatically now, so `CriteriaSimpleSerializer` is just an alias for it. Updated `tests/integration/criteria/tree/load_example/test_load_example.py` to match the real song data the kit's `0.14.1` release replaced its placeholder fixtures with.
- Bumped `the-music-tree-genre-kit` to `v0.14.0` and converted `Genre` from a `Criteria` proxy model into a real multi-table-inheritance (MTI) subtype (`class Genre(AbstractGenreCriteria, Criteria)`), following the kit moving `side` off the shared `AbstractCriteria` base into a new `AbstractGenreCriteria` mixin. `Genre` now owns `side` on its own table (`grow_genre`, linked back to `grow_criteria` via `criteria_ptr`) instead of it living on `Criteria` directly; `Tag` remains a proxy model, unaffected structurally, though `TagManager` now inherits the kit's `AbstractTagManager` for consistency with `GenreManager`. Added a hand-authored migration, `grow/migrations/0016_genre_mti.py`, that creates the new `Genre` table, copies each genre-type `Criteria` row's existing `side` value onto its new `Genre` row, then drops the now-redundant `side` column from `grow_criteria`. Because `Genre` and `Criteria` are now distinct concrete models, an instance's self-referential `parent`/`ascendants` (declared on `Criteria`) no longer compares equal (`==`) to a `Genre` instance sharing the same pk — comparisons needing that must use `.pk` instead; updated the affected assertions in `tests/integration/criteria/tree/test_get.py` and `tests/integration/criteria/tree/import/test_structure.py` accordingly.

### Fixed

- **Genre `side` missing from `genre-playlists/` list responses**: `CriteriaSimpleSerializer.get_side()` and `CriteriaDetailedSerializer.get_side()` read `side` directly off the shared MTI base `Criteria` object, where the field no longer lives since `Genre` became a real MTI subtype (see `[Unreleased]` "Changed" above) — it silently returned `None` via `getattr(obj, "side", None)` for every genre served through a code path that fetches base `Criteria` instances, most notably `CriteriaPlaylistSimpleSerializer.criteria` on the `genre-playlists/` list endpoint. Both `get_side()` methods now resolve `side` via the reverse `.genre` MTI accessor, which safely returns `None` for non-genre criteria (e.g. `Tag`). Added regression tests exercising both serializers directly against a base `Criteria` instance (`tests/unit/serializer/model/criteria/test_simple.py`, `tests/unit/serializer/model/criteria/test_detailed.py`) and an integration test against the real `genre-playlists/` endpoint (`tests/integration/criteria/playlist/test_genre_playlist_list.py`).
- **`CORS_ALLOWED_ORIGIN_REGEXES` env var had no effect**: `grow/settings.py` only ever parsed `CORS_ALLOWED_ORIGINS` (exact-match origins); the regex-based env var was set in infrastructure config but never read into a Django setting, so `django-cors-headers` silently treated it as empty. Every regex-based allowlist entry (Vercel preview deployments, PR-preview subdomains, local dev origins) has been a no-op. Now parsed the same way as `hear-the-music-tree-api`.

## [1.1.0] - 2026-08-28

### Added

- `seed_prototype_tree` management command now requires `--songs-file <path>`, pointing at an externally-supplied JSON file of song entries (never committed to git) instead of a bundled fixture — fails fast if omitted rather than silently falling back to a small default dataset. Removed the now-unused `grow/data/prototype_songs.json`. Reuses the existing `SongExampleImportSerializer` validation and the kit's `import_example_songs`, which was made bulk-efficient in `the-music-tree-genre-kit` `v0.11.0` (single batched genre/artist lookup and `TrackPlaylistRel.bulk_create` instead of per-row queries). Re-pinned `the-music-tree-genre-kit` to `v0.11.0` for this.

### Fixed

- **Container healthchecks rejected with `DisallowedHost`**: `ALLOWED_HOSTS` was built purely from the `ALLOWED_HOSTS` env var, which only carries the externally exposed hostname. Both healthchecks reach the app over loopback — the `HEALTHCHECK` in [`Dockerfile`](Dockerfile) hits `127.0.0.1`, and Coolify's own container healthcheck (not configurable) execs against `localhost` — so Django answered them with a 400 and the container was marked unhealthy, rolling back the deployment. `grow/settings.py` now calls `the-music-tree-api-kit`'s shared `add_loopback_hosts`, appending `127.0.0.1`, `127.0.0.1:<APP_PORT>`, `localhost` and `localhost:<APP_PORT>`. `hear-the-music-tree-api` uses the same helper rather than duplicating the fix. This does not widen the real attack surface — loopback is not externally reachable.
- **`Dockerfile` healthcheck probed the wrong port when `APP_PORT` is unset**: it defaulted to `8001` while [`scripts/start-server.sh`](scripts/start-server.sh) binds gunicorn to `${APP_PORT:-8000}`, so with no `APP_PORT` in the environment (as on Coolify) the probe hit a closed port and failed with `ConnectionRefusedError` regardless of app health. The healthcheck now defaults to `8000`, matching what the server binds. `docker-compose.yml` is unaffected — it sets `APP_PORT` explicitly.

### Changed

- Re-pinned `the-music-tree-genre-kit` to `v0.12.0`, which itself re-pins `the-music-tree-api-kit` to `v0.5.0` (the version adding `add_loopback_hosts`).

## [1.0.0] - 2026-08-27

### Added

- Added a second, read-only "prototype" static-API-key identity alongside the existing system user: `PROTOTYPE_USERNAME`/`GROW_PROTOTYPE_API_KEY` settings, a prototype `User` bootstrapped via migration (with its own criteria-less `CriteriaPlaylist` rows), and enforcement in `ApiKeyAuthentication`/`GrowModelViewSet` so any write attempt authenticated with the prototype key returns `403 Forbidden`. Reads behave identically to the system user.
- New `seed_prototype_tree` management command (re)seeds the prototype user's genre tree and tracks from dedicated fixtures (`grow/data/prototype_genre_tree.json`, `grow/data/prototype_songs.json`), reusing the kit's existing `import_criteria_tree`/`import_example_songs` manager methods and serializers rather than reimplementing the import logic. Re-running the command is safe: it now clears the prototype user's tracks before re-importing the genre tree, working around a real bug the command's own idempotency test surfaced — `Track.genre` is `on_delete=DO_NOTHING`, so a second `import_criteria_tree` call (which wipes and rebuilds the genre tree) leaves existing tracks pointing at now-deleted genre rows, causing an `IntegrityError` on commit. This same failure mode existed in the kit-provided `tree/load-example` endpoint (`GenreViewSet`) on a second call for a user with existing tracks — fixed below.

### Changed

- Expanded `grow/data/prototype_genre_tree.json` (seeded by `seed_prototype_tree`) from ~66 lines / 4 roots to ~1100 nodes across the 8 canonical roots (`Reggae/Dub`, `Electronic`, `Classical`, `Jazz`, `Rock`, `Hip-Hop`, `Disco/Funk`, `Mainstream Pop`), each core root split into a `(core)` branch plus a named pop-crossover branch (`Pop Rock`, `Pop Hip-Hop`, `Pop Funk/Disco`, `EDM`, `Pop Jazz`, `Pop Reggae` — `Classical` has core only, `Mainstream Pop` stays flat) tagged via `"side": "pop"`, giving the frontend wheel-visualization component a much richer demo tree to render. `grow/data/prototype_songs.json`'s `"Boom Bap (core)"` `genre_name` reference updated to `"Boom Bap"` to match the restructured tree.

- `POST tree/load-example` now also (re)seeds the user's example songs, not just the example genre tree: `GenreViewSet.on_example_tree_loaded` loads the bundled `song_example.json` fixture (from `the-music-tree-genre-kit`'s `DATA_DIR`, already reused by this app) through the kit's `SongExampleImportSerializer` and `YoutubeTrack.objects.import_example_songs`. Also added `SongExampleTreeMixin[YoutubeTrack]` to `YoutubeTrackViewSet`, exposing a standalone `POST library/youtube/songs/load-example` action. **Behavior change:** because `import_example_songs` wipes-then-reseeds all of the user's tracks, `tree/load-example` now deletes the user's entire `YoutubeTrack` library on every call, not just genre associations as before (the old `YoutubeTrack.objects.filter(user=...).update(genre=None)` reset is removed as redundant).

- Internal refactor, no API change: `CriteriaDetailedSerializer`'s `tracks`/`tracks_count`/`tracks_archived_count` fields and `CriteriaPlaylistMinimumSerializer` now source their DRF field/serializer definitions from `the-music-tree-genre-kit`'s new `build_criteria_detailed_tracks_fields`/`build_criteria_playlist_minimum_serializer` builders instead of hand-duplicating them, now that both are backed by the kit's shared `TrackMixin`/`CriteriaPlaylist`.
- Re-pinned `the-music-tree-genre-kit` to `v0.9.0`, which adds the `build_criteria_detailed_tracks_fields`/`build_criteria_playlist_minimum_serializer` builders this refactor adopts.
- Bumped `the-music-tree-genre-kit` to `v0.10.0`, which renames the bundled `genre_example_tree.json`'s top-level `"Pop"` root to `"Mainstream Pop"` — needed by a frontend wheel-visualization component that requires a root with that exact name.
- Updated `grow/data/prototype_genre_tree.json` (seeded by `seed_prototype_tree`) to satisfy the same frontend wheel-visualization component's requirements: added a `"Mainstream Pop"` root with an illustrative subtree, and tagged one direct child of each of the other three roots (`Techno`, `Metal`, `Trap`) with `"side": "pop"` so every non-`Mainstream Pop` root has at most one untagged ("core") direct child, renaming that remaining child to make the core/pop split explicit (`House` → `House (core)`, `Alternative Rock` → `Alternative Rock (core)`, `Boom Bap` → `Boom Bap (core)`). `grow/data/prototype_songs.json`'s `"Boom Bap"` `genre_name` reference updated to match.

### Fixed

- Fixed `youtube_video_id` serializing as `null` in `track_playlist_relations[*].track` on `GET genre-playlists/{uuid}/` (and the equivalent `tag-playlists`/`criteria-playlists` detail endpoints): `TrackPlaylistRelWithoutPlaylist.get_track()` serialized the base `Track`/`KitTrack` instance through `YoutubeTrackDetailedSerializer` instead of downcasting via `.youtubetrack`, so DRF silently rendered youtube-only fields as `null`. Now downcasts explicitly, with `select_related`/`prefetch_related` added to the affected viewsets to avoid an N+1 from the extra join. `YoutubeTrack.youtube_video_id` is also now a required, non-nullable field (migration `0014_alter_youtubetrack_youtube_video_id`) — no existing rows had a null value, so no data backfill was needed. Added a regression test hitting the live endpoint.

- Fixed `GET genre-playlists/{uuid}/` (and the equivalent `tag-playlists`/`criteria-playlists` detail endpoints) raising a `500` on every call: `CriteriaPlaylistDetailedSerializer.tracks_archived_count` declared a `source=` matching its own field name, which DRF rejects with an `AssertionError` as soon as the serializer's `.fields` are accessed — the same redundant-`source=` bug already fixed elsewhere for `ArtistSimpleSerializer`/`ArtistDetailedSerializer`/`AlbumDetailedSerializer`. Added a regression test hitting the live endpoint.

- Fixed `POST tree/load-example` (`GenreViewSet`) raising an `IntegrityError` on a second call for a user with existing tracks: `Track.genre` is `on_delete=DO_NOTHING`, so the kit's `load_example_tree` action wiping and rebuilding the genre tree left existing tracks pointing at now-deleted genre rows, and the deferred FK violation only surfaced at commit (masked by the custom exception handler as a generic `500`). `GenreViewSet.load_example_tree` now clears the user's `YoutubeTrack` library before delegating to the kit's mixin, mirroring the identical fix already applied to `seed_prototype_tree` above. `YoutubeTrackViewSet`'s `songs/load-example` action (`SongExampleTreeMixin`) doesn't touch `Genre` at all, so it isn't affected. Added a `TransactionTestCase`-based regression test (`tests/integration/criteria/tree/load_example/test_load_example_idempotent.py`) that calls `tree/load-example` twice and asserts both succeed.

- Fixed `seed_prototype_tree` raising `StringDataRightTruncation` on the songs-import step: `grow/data/prototype_songs.json`'s placeholder `youtube_video_id` values (`PROTO_PLACEHOLDER01`, etc., 19 chars) exceeded the column's `varchar(11)` limit. Shortened to `PROTO_PH_01` etc. (11 chars).

- Fixed `Criteria`'s `side` field (`core`/`pop`, added to `AbstractCriteria` in genre-kit v0.8.0) never appearing in the detailed JSON output: the DB column and migration existed, but grow's hand-maintained `CriteriaOutputFieldKey` enum and `CriteriaDetailedSerializer.Meta.fields` were never updated to include it, so the API silently dropped it. Added `SIDE` to the enum and to the serializer's fields, plus tests asserting `side` round-trips through `CriteriaDetailedSerializer`. This local enum stays a plain duplicate of the kit's rather than being mechanically derived from it — see the investigation notes in the corresponding PR for why.

- Regenerated `uv.lock`, which was never re-run after `pyproject.toml` was repinned to `the-music-tree-genre-kit` v0.7.1 (transitively pulling `the-music-tree-api-kit` v0.3.0): the lock still resolved the old api-kit v0.2.0, which has no `the_music_tree_api_kit.view.middleware` package, so the `HEALTHCHECK`-passing production image built with `uv sync --frozen` crashed every Gunicorn worker on boot with `ModuleNotFoundError` and Coolify rolled back the deploy.
- Added a `HEALTHCHECK` to the Dockerfile: it was missing entirely, so a Coolify deploy of the production image (which has no `curl`/`wget`, unlike `hear-the-music-tree-api`'s image) would report unhealthy. Uses the same `python3 -c "...urllib..."` probe already used by `docker-compose.yml`'s local healthcheck, so no extra package install is needed.
- Fixed `ArtistSimpleSerializer`, `ArtistDetailedSerializer`, and `AlbumDetailedSerializer` raising an `AssertionError` on first use: each declared `tracks_archived_count` with a `source=` matching its own field name, which DRF rejects as redundant. Discovered while adding coverage for `Album`/`Artist`, which were previously untested.
- Fixed `CriteriaPlaylist.DoesNotExist` on deleting a root `Genre` or `Tag`: the catch-all criteria-less `CriteriaPlaylist` row per `(user, type)` that `TrackManager`/`CriteriaPlaylistManager` assume exists was never created. A `post_save` signal now bootstraps it for new users, and a data migration backfills it for existing users.
- Fixed tracks directly attached to a deleted root `Tag` being silently orphaned instead of moved to the criteria-less playlist: `CriteriaManager._on_before_delete` looked up "direct tracks to transfer" via the `Genre`-specific FK-leaf relation, which is always empty for `Tag`. Added regression tests covering root `Genre` deletion, root `Tag` deletion, and a track transitioning to genreless.
- Fixed a startup crash on any database that had already run the original `0001_initial`: that migration file was later hand-edited to rename the local `Playlist` model's index from `playlist_user_uuid_idx` to `grow_playlist_user_uuid_idx`, avoiding a collision with the shared genre-kit's own identically-named index on its `Playlist` table (`0004_playlist`), but the edit only affects fresh databases — staging/production still physically carried the old index name, so `0004_playlist` crashed every Gunicorn worker with a duplicate-index error. A new migration renames the physical index directly (Postgres only, `IF EXISTS`, no Django state change) ahead of `0004_playlist` via `run_before`, regardless of when either database was created.

### Changed

- Re-pinned `the-music-tree-api-kit` to `v0.2.0` and `the-music-tree-genre-kit` to `v0.3.0`; `TrackPlaylistRel`, `TrackPlaylistRelManager`, `CriteriaPlaylist`, and `CriteriaPlaylistManager` are now thin subclasses of the shared kit abstractions, removing near-duplicate logic previously maintained separately from `hear-the-music-tree-api`. No schema or behavioral changes.
- Re-pinned `the-music-tree-genre-kit` to `v0.4.0` and removed `CriteriaManager._get_direct_tracks`/`_on_before_delete`: this orchestration is now hoisted into the kit's `AbstractCriteriaManager`, which fixes the same root-`Tag`-deletion bug generically for any consuming app. `GenreManager._get_direct_tracks` is unchanged. No schema or behavioral changes.
- Re-pinned `the-music-tree-genre-kit` to `v0.5.1`; grow's local `Track` model is retired in favor of the kit's shared `Track` (Django MTI) — `UploadedTrack`/`YoutubeTrack` now inherit it directly. `TrackManager` is a thin subclass of the kit's `AbstractTrackManager`, removing near-duplicate genre-playlist and album/artist orphan-cleanup logic. Data migration copies existing `grow_track` rows into the kit's table under the same PK before dropping grow's local table; both steps are separate migrations so a bad deploy can be halted after the additive step without a destructive rollback. Playlist-membership access (`instance.playlists`, used by the youtube/uploaded track serializers) is reconstructed via a new `TrackConvenienceMixin.playlists` property, since the kit's `Track` intentionally has no `playlists` M2M field. No API-visible behavior change.
- `settings.TRACK_MODEL` now points at `grow.YoutubeTrack` directly instead of the kit's base `Track`. grow has exactly one concrete track type, so `TrackConvenienceMixin.resolve_concrete()` and its disambiguation logic are removed entirely, along with the dead `UploadedTrack` model/table (no live API surface). Serializers and `Play.content`/`content_type` resolution now reference `YoutubeTrack` directly instead of downcasting from the shared base `Track`.
- Added unit tests for `Album`/`AlbumManager`, `ArtistManager`, and `ArtistSimpleSerializer`, raising total coverage from 82.43% to 85.55%, and raised the CI-enforced coverage floor (`pytest-cov`'s `--cov-fail-under`) from 76% to 85% accordingly.
- **Breaking:** re-pinned `the-music-tree-genre-kit` to `v0.7.2` (transitively pulling `the-music-tree-api-kit` v0.4.0) and wired in the shared `CamelToSnakeMiddleware`, plus `djangorestframework-camel-case`'s `CamelCaseJSONRenderer`/`CamelCaseJSONParser` family as `REST_FRAMEWORK`'s default renderer/parser classes. All JSON request/response bodies are now camelCase instead of snake_case, matching `hear-the-music-tree-api`'s existing contract — clients must be updated accordingly.
- Re-pinned `the-music-tree-genre-kit` to `v0.8.0`, which adds a `side` (`core`/`pop`) field to `Criteria`; a migration adds the corresponding `side` column to grow's `Criteria` table.
