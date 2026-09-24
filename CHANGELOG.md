# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## Guidelines for Contributors

- Add entries to the `[Unreleased]` section under the appropriate category: `Added`, `Changed`, `Improved`, `Deprecated`, `Removed`, `Fixed`.
- Group related changes together; write clear, user-focused descriptions rather than raw git log dumps.
- Mention tests within the related feature or fix entry — "Test" is not its own category.

## [Unreleased]

### Added

- Admin edits to genres and songs now win over the next pipeline sync: an admin rename, reparent, or
  re-tag locks that field against the daily rebuild, and `POST /v1/genres/{id}/exclude/` soft-removes
  a Wikidata-backed genre without it reappearing on the next import.
- `GET /v1/genres/{id}/history/` and `GET /v1/library/youtube/songs/{id}/history/` return each
  genre's/song's actor+timestamp+action edit history.

### Changed

- Bumped `the-music-tree-genre-kit` pin to `v0.25.0` (picking up `the-music-tree-api-kit` `v0.6.0`'s `AppModelViewSet._get_manager_write_kwargs` hook).

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
