# grow-the-music-tree-api

Reference genre/tag/tree service for `grow-the-music-tree-frontend`.

Depends on [`the-music-tree-genre-kit`](https://github.com/BehindTheMusicTree/the-music-tree-genre-kit) for shared genre/tag/criteria/tree logic.

## Table of Contents

- [grow-the-music-tree-api](#grow-the-music-tree-api)
  - [Table of Contents](#table-of-contents)
  - [Features](#features)
  - [Requirements](#requirements)
  - [Setup](#setup)
    - [Docker Compose (recommended)](#docker-compose-recommended)
    - [Local (uv + external Postgres)](#local-uv--external-postgres)
    - [Prod data locally](#prod-data-locally)
  - [Environment variables](#environment-variables)
  - [API](#api)
  - [Tests](#tests)
- [Performance](#performance)
  - [Data sources and licenses](#data-sources-and-licenses)
  - [License](#license)

## Features

- Genre and tag criteria trees, with bulk tree import and export
- Playlists automatically derived from genre/tag criteria, plus manually curated playlists
- Artist, album, and song catalog (every MusicBrainz song, with or without a genre or YouTube video), with play tracking
- Every MusicBrainz song, including songs with no video or no genre, loaded by a staged bulk import (gzip NDJSON parts, Postgres `COPY`, set-based merge); the library list shows only songs with both a video and a genre
- Public reads of one canonical reference dataset (rows with no owner); writes via Google sign-in (admin) or the pipeline API key
- `/health/` endpoint for uptime and database checks

## Requirements

- Python 3.14
- [uv](https://docs.astral.sh/uv/)
- Docker + Docker Compose (for Postgres, or to run the full stack containerized)

## Setup

### Docker Compose (recommended)

```bash
docker compose up
```

Starts Postgres (`db`) and the API (`api`) with dev-friendly defaults already set in `docker-compose.yml` — no env file needed. The API is served on `http://localhost:8001` (via `manage.py runserver` with the repo mounted for live reload) and exposes a health check at `GET /health/`.

On an empty DB, `api` seeds it in the background with the pinned prod Gold snapshot in `perf/fixtures/` (`scripts/seed_dev_db.py`: genre trees, then about 9k songs, through the same import endpoints as the nightly sync), so the genre tree works out of the box. It lacks admin curation: restore prod data (below) when you need it. To reseed: `docker compose down -v && docker compose up`.

### Local (uv + external Postgres)

```bash
uv sync
```

Set the required environment variables (see below), then:

```bash
uv run manage.py migrate
uv run manage.py runserver
```

### Prod data locally

```bash
RCLONE_CONFIG=~/.config/rclone/gtmt-backup.conf R2_BACKUP_BUCKET_NAME=btmt-backups ./scripts/restore-prod-db.sh
```

**Legacy archives:** this script erases the local schema before restoring. Use the [legacy recovery procedure](docs/operations/backup-recovery.md) for backups made before migration 0101.

Replaces the Docker Compose `db` with the latest prod backup (Coolify's daily `pg_dump` to Cloudflare R2), then restarts `api`/`worker`, which apply the current branch's migrations. Includes admin curation that the pipeline Gold exports in `perf/fixtures/` lack. The dump holds only the public canonical dataset, so it is safe on a laptop. Requires [rclone](https://rclone.org/) and a config with an `[r2]` remote (`type = s3`, `provider = Cloudflare`, `endpoint = https://<account-id>.r2.cloudflarestorage.com`) using a **read-only** R2 token scoped to the backup bucket, not the VPS's read/write one. Token setup: infrastructure's [`docs/guides/cloudflare-r2-backup-setup.md` § 5](https://github.com/BehindTheMusicTree/infrastructure/blob/main/docs/guides/cloudflare-r2-backup-setup.md#5-local-dev-read-only-token-prod-db-restore).

To time a migration on prod-sized data without touching the local DB, see [Migration rehearsal](docs/operations/migration-rehearsal.md).

## Environment variables

| Variable                 | Required | Default   | Notes                                                                                                      |
| ------------------------ | -------- | --------- | ---------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`             | yes      | —         | Django secret key                                                                                          |
| `CURATION_API_KEY`           | yes      | —         | Static API key (`X-API-Key`) for the `curator` role: writes curation entries only                      
| `PIPELINE_API_KEY`           | yes      | —         | Static API key checked against the `X-API-Key` header                                                      |
| `GOOGLE_OAUTH_CLIENT_ID` | yes      | —         | Google OAuth client ID; the expected `aud` of Google ID tokens                                             |
| `YOUTUBE_API_KEY`        | yes      | —         | YouTube Data API key checking a manually set song video (`PATCH library/songs/{uuid}/`); startup fails without it |
| `ADMIN_GOOGLE_SUB`       | yes      | —         | Google account `sub` that gets the `admin` role; any other verified Google account is a read-only `viewer` |
| `DATABASE_URL`           | yes      | —         | Postgres connection string, parsed via `dj-database-url`                                                   |
| `DEBUG`                  | no       | `false`   |                                                                                                            |
| `ALLOWED_HOSTS`          | no       | `""`      | Comma-separated                                                                                            |
| `GIT_COMMIT`             | no       | —         | Surfaced as `commit` in `/health/`; baked into the image by the build workflow                             |
| `APP_PORT`               | no       | `8001`    | Only used by Docker Compose                                                                                |

There's no `.env.example` — Docker Compose supplies dev defaults for all of the above inline.

## API

Reads (`GET`) on `/v1/*` and `/health/` are public. Writes (`POST`/`PUT`/`PATCH`/`DELETE`) require an `Authorization: Bearer <Google ID token>` for the `ADMIN_GOOGLE_SUB` account. The `X-API-Key` header (set to `PIPELINE_API_KEY`) is for the nightly pipeline and can only write to `genres/tree/import/`, `library/songs/songs/import-runs/` and `artists/import-runs/` and `regions/map/import-runs/` (create, part upload, commit), `pipeline/imports/unresolved-genre-tags/`, `genealogy/import/`, `curation/wikidata-resolutions/`, `curation/wikidata-items/`, `pipeline/runs/` (`full` only), `pipeline/runs/claim/` and `pipeline/runs/{uuid}/`, and read `curation/export/` and `pipeline/runs/latest/`; other writes with it return 403 `permission_denied`. The `X-API-Key` header set to `CURATION_API_KEY` is the `curator` role for agents: it can only read and write `curation/<list>/entries/` and `curation/edges/` (history attributes its writes to the `curation-bot` user), and `curation/export/` stays pipeline/admin-only. No credentials returns 401 `authentication_required`, an invalid or expired token 401 `invalid_token`, and a verified non-admin Google account 403 `permission_denied`. `GET /v1/auth/me/` returns the caller's `{"role", "email"}` (401 when anonymous). Reference data has no owner (`user IS NULL`) and is the same for every caller; a Google sign-in creates a `User` keyed by the account's `sub`, which owns nothing yet.

| Path                          | Description                                          |
| ----------------------------- | ---------------------------------------------------- |
| `GET /health/`                | Health check (no auth)                               |
| `/v1/albums`                  | Albums                                               |
| `/v1/artists`                 | Artists (list, detail with MusicBrainz details, `image` (`{url, pageUrl, author, license, licenseUrl}` or null; show with its attribution), members, links and release-group albums, `{uuid}/genre-counts/` (sparse per-genre-playlist song counts of the artist's footprint), + `import-runs/`) |
| `/v1/genealogy`               | `GET` latest music-tradition genealogy document (public; `ETag` = checksum, `304` on `If-None-Match`, 404 before the first import); `POST import/` stores a new snapshot from the pipeline's `4_genealogy.json` (pipeline key or admin; 201 created, 200 unchanged) |
| `/v1/regions/map`              | `GET` latest region map index (public; `ETag` = checksum, `Cache-Control: no-cache`, gzip when accepted, `304` on `If-None-Match`, 404 before the first import): the per-region stats and genre hierarchy, plus `tileset`, the sha256 of the immutable vector tileset `regions/<sha256>.pmtiles` the pipeline published to object storage (the geometry is not stored or served here). `import-runs/` takes the pipeline's `5_region_map/parts` (full runs only, a single NDJSON line `{path: "index.json", sha256, document}`, the sha256 checked over the canonical JSON); the merge checks `tileset` is a sha256, `files` is absent and the index lists only known genres (`tradition` relations excepted), replaces the snapshot atomically, and records an unchanged index as skipped. The pipeline must publish the tileset before committing the run |
| `/v1/regions/map/genres`       | `GET` (public) the genres the latest index refers to by Wikidata id, one row each (`wikidataId`, `uuid`, `name`, `treeName`, `genrePlaylistUuid`, `isUmbrella`, `viewsCount`), so a client can search overviews and regional genres in memory. Cached on the snapshot checksum plus the genre tree version token; 404 before the first import |
| `/v1/genres`                  | Genre criteria tree (CRUD + `search/?q=&limit=&tree_name=` (public ranked typeahead over canonical and regional genres, overviews included), `{uuid}/overview/`, `{uuid}/set-root/`, `{uuid}/exclude/` (body `{"category": "theme"\|"technique"\|"out_of_scope"\|"duplicate"}`), `tree/`, `tree/import/`, `name-conflicts/`, `name-conflicts/validate/`, `unaccepted-roots/`, `unaccepted-roots/accept/`) |
| `/v1/tags`                    | Tag criteria tree (CRUD + `{uuid}/overview/`, `tree/`, `tree/import/`) |
| `/v1/playlists`               | Playlists (CRUD + `{uuid}/tracks/`; on every playlist route, `tracks/?from=<track uuid>` starts the list at that track in play order, 404 if it is not in the playlist, 400 if not a UUID) |
| `/v1/manual-playlists`        | Manual playlists (CRUD + `{uuid}/tracks/`)           |
| `/v1/genre-playlists`         | Playlists derived from the genre tree (read-only, + `{uuid}/tracks/`) |
| `/v1/tag-playlists`           | Playlists derived from the tag tree (read-only, + `{uuid}/tracks/`) |
| `/v1/plays`                   | Play records                                         |
| `/v1/library/songs`      | Songs (CRUD + `songs/import-runs/`, `?genre=`, `?artist=`, `?playable=`, `?from=<uuid>`, `?ordering=title\|-title\|albumYear\|-albumYear`; detail adds `firstReleaseYear` and `essentialGenres`). `search/?q=&limit=&genre=any\|with\|without&playable=` is the public ranked typeahead over titles and artist names, 503 until `manage.py rebuild_song_search` has run once ([`docs/api/songs.md`](docs/api/songs.md)) |
| `/v1/curation/lists/`         | The pipeline curation lists: `{name, keyColumns, columns, description}` (admin only) |
| `/v1/curation/{list}/entries/` | Curation entries of one list (`GET`/`POST`, `{uuid}/` `PATCH`/`DELETE`; admin only). Body `{"row": {<csv column>: value}}`, `row` keys stay snake_case |
| `/v1/curation/edges/`         | The curated genre edges, one `GenreEdgeRule` per row (`GET` paginated, filters `item_id`, `relation`, `q`; `POST`; `{uuid}/` `PATCH`/`DELETE`; admin or `curator`). Body `{relation: canonical_parent\|regional_genre_parent\|regional_overview\|secondary_parent, itemId, parentItemId?, action?, excludeOtherParents?, reason?}`: `parentItemId` null makes a canonical root (needs `excludeOtherParents: true`), `action` (`add`\|`remove`) only on `secondary_parent`, `excludeOtherParents` on every other relation. A second primary parent for an item and relation, or a second rule for a pair `(itemId, parentItemId)`, is a 400 (the admin genre edit replaces instead). Replaces the five legacy lists `canonical_parent`, `accepted_canonical_roots`, `regional_genre_parent`, `regional_overviews` and `secondary_parents` |
| `/v1/curation/export/`        | Every list as CSV-ready rows keyed by list name, plus `edges` (`genre_edges.csv` rows) and `exported_on` (ISO 8601, the export's instant), plain snake_case JSON (`X-API-Key` or admin) |
| `/v1/curation/wikidata-resolutions/` | `POST {remaps: [{list, key, column, from, to}], review: [{list, key, column, itemId, reason: redirect_conflict\|missing\|not_in_tree\|invalid_rule\|exclusive_parent_regional, target?, evidence?}]}`, the pipeline's Wikidata resolution of curation item ids (`X-API-Key` or admin). Each remap rewrites the redirected id `from` to `to` in the `column` of entry `key` of `list`, recording history with a null actor; a remap clashing with another entry becomes a `redirect_conflict` review item, one whose entry or `from` id is gone is skipped. An edge item designates its rule by `rule_id` (instead of `list` + `key`, `column` `item_id` or `parent_item_id`); the legacy `list` + `key` of the five edge lists still resolves. `evidence` is the Wikidata facts seen at detection, unknown keys rejected: `{label?, modified?, instanceOf?, subclassOf?: [{id, label}], hasIndigenousTo?, conflictList?}`. Replaces every review item. Returns `{remappedCount, reviewCount}` |
| `/v1/curation/wikidata-items/` | `POST {items: [{id, label}]}`, the pipeline's catalog of every Wikidata item it knows (pruned ones and `LOCAL:` ones included), `X-API-Key` or admin. Replaces the whole catalog; names the item ids that aren't in the canonical tree. Returns `{itemCount}` |
| `/v1/curation/items/` | `GET ?q=` (admin) searches item ids by name or id across the canonical tree, the catalog and pending additions: `{results: [{id, label}]}`, 400 without `q` |
| `/v1/curation/review/`        | `GET` the last report's review items, the ids the pipeline dropped: `[{ruleId, list, key, column, itemId, reason, target, evidence, reportedOn}]` (`ruleId` set for an edge rule) (`evidence` null when not reported, always null on API-side remap conflicts) (admin only) |
| `/v1/pipeline/runs/`          | `GET` the run requests, newest first, paginated (admin only). `POST {kind: curation\|full\|sync}` queues a pipeline run: a rebuild from current curation, a full ingestion, or a replay of the last complete Gold output into grow. An admin's request has `trigger: manual` and `requestedBy` their email; the `X-API-Key`'s (the nightly) has `trigger: scheduled`, `requestedBy: null`, and may only request `full` (400 otherwise, so `sync` is admin-only). 409 if any run is queued or running, 400 for `curation` with no edit pending. A request is `{uuid, kind, trigger, requestedBy, status, stage, stageCurrent, stageTotal, error, cancelRequested, requestedOn, startedOn, heartbeatOn, finishedOn}`, `status` `queued\|running\|succeeded\|failed\|superseded\|cancelled\|expired`, `stage` `fetching_rules\|ingesting_musicbrainz\|ingesting_wikidata\|building_songs\|building_genres\|matching_songs\|importing_tree\|uploading_songs\|merging_songs\|uploading_artists\|merging_artists` |
| `/v1/pipeline/runs/latest/`   | `GET` the newest run request, 204 if none (`X-API-Key` or admin) |
| `/v1/pipeline/runs/claim/`    | `POST` starts the oldest queued request (`running`), or marks a `curation` one `superseded` if no edit is pending anymore; 204 if none queued (`X-API-Key` or admin) |
| `/v1/pipeline/runs/{uuid}/`   | `PATCH {stage?, stageCurrent?, stageTotal?, status?: succeeded\|failed\|cancelled, error?}` on the running request, an empty body being a heartbeat; a new `stage` resets the progress counts, a `status` sets `finishedOn`; `cancelRequested: true` in the response means stop the run and report `cancelled`; 409 if not running (`X-API-Key` or admin). A running request with no PATCH for 30 min becomes `expired` |
| `/v1/pipeline/runs/{uuid}/cancel/` | `POST` cancels a queued request, or sets `cancelRequested` on a running one; 409 if neither (admin only) |
| `/v1/pipeline/imports/`       | Pipeline import history, newest first, paginated, `?kind=canonical_tree\|regional_tree\|songs\|unresolved_genre_tags\|genealogy\|region_map`: `{kind, importedOn, count, skippedCount}` (admin only). Recorded on every `X-API-Key` tree or songs import (`skippedCount`: songs with no matching genre), not on admin imports |
| `/v1/pipeline/imports/latest/` | Newest run per kind: `{canonicalTree, regionalTree, songs, unresolvedGenreTags, genealogy, regionMap}`, each a run or `null` (admin only) |
| `/v1/pipeline/imports/unresolved-genre-tags/` | `POST {"unresolvedGenreTagCount": n}`: records the pipeline's count of song genre tags it couldn't match to a genre, returns the run (`X-API-Key` or admin) |

An admin edit of a wikidata-backed genre also upserts the curation rule that makes the pipeline reproduce it, with reason `grow admin edit by <pseudo>`: a rename goes to `label_overrides`, a canonical reparent to a `canonical_parent` edge (`exclude_other_parents`), a root acceptance to a parentless `canonical_parent` edge, and an exclusion to `<category>_genres`. Edits no list expresses return 400: a reparent to a root, under an app-created genre, or in the regional tree (grow can't tell a `regional_overview` edge from a `regional_genre_parent` one). Genres without a `wikidataId` are app-created, absent from the pipeline's output, so their edits only lock the row.

Full request/response details per resource are documented in [`docs/api/`](docs/api/).

A [Bruno](https://www.usebruno.com/) collection for manual testing is at [`bruno/Track/`](bruno/Track/) — open it in the Bruno app, select the `local` environment, and set the `API_KEY` secret to your `PIPELINE_API_KEY`.

## Tests

```bash
uv run pytest
```

Tests run against an in-memory SQLite database and need no environment variables.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy grow
```

## Performance

Three gates keep endpoints fast. The query budgets run in `Pytest` (required); `Perf` is not a required check yet. Changing a budget or an SLO is a deliberate, reviewed diff, not a way to make CI pass.

- **Query budgets** (`tests/integration/perf/test_query_budgets.py`, part of `uv run pytest`): each endpoint must run a fixed number of queries whatever the number of rows, and exactly its `BUDGETS` entry. A gain lowers the budget in the same PR.
- **Latency SLOs** (`perf/`, CI job `Perf`): median latency per endpoint on Postgres (p95 is printed too), seeded with a pinned snapshot of the prod pipeline's Gold exports (`perf/fixtures/`), imported through the same endpoints and in the same order as the nightly sync.
- **A/B regression gate** (CI job `Perf` on PRs, `scripts/perf_ab.sh`): the PR's base and head run `perf/` in turn on the same runner (base, head, base, head), each on its own seeded database. Before every measured round, `VACUUM (FREEZE, ANALYZE)` resets visibility and planner statistics: rolled-back reparenting still grows physical tables and can otherwise trigger JIT compilation only in later rounds. `perf/compare.py` pools each side's timings and fails a scenario that is more than `RATIO` times slower **and** more than `FLOOR_MS` slower than the base, or that runs more queries. A suspected regression gets two more rounds before the verdict. A side whose round medians differ by as much is `unstable` and fails too: its pooled median would sit between two query plans, and the summary shows each round's p50. This catches what an absolute SLO can't: a 13 ms endpoint going to 130 ms under a 150 ms SLO. The table lands in the job summary. Pushes to `main` and `develop` judge the SLOs only; `workflow_dispatch` compares a ref with itself to measure noise.
- **Accepting a regression** (a deliberate trade-off, for example a feature that must do more work): add the `perf-regression-accepted` label to the PR, which reruns `Perf` with slowdowns and query increases reported but not failed. SLOs still apply.

The absolute SLOs use 3× the slowest side's pooled median across five CI self-comparisons on 2026-11-07, rounded up to 10 ms (100 ms when the ceiling is at least 1 s). For example, artist genre counts measured about 9 ms (30 ms SLO), the largest genre's track page about 84 ms (260 ms), and the 100-row genre playlist list about 155 ms (470 ms). This covers runner-speed variation while the A/B gate still catches relative regressions. Calibration runs: [1](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42382519148), [2](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42382845469), [3](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42383175534), [4](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42383477978), [5](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42383729328).

A red `Perf` is a regression until a same-runner A/B or an `EXPLAIN (ANALYZE, BUFFERS)` shows otherwise. Never merge over it.

```bash
docker run -d --name grow-perf-pg -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:55432:5432 postgres:16-alpine
PERF_DATABASE_URL=postgres://postgres:postgres@127.0.0.1:55432/postgres uv run pytest perf --no-cov -s --ds=perf.settings --reuse-db
# A/B against develop: check it out in a scratch worktree, then (about 5 min: two seeds, four runs)
git worktree add --detach /tmp/grow-perf-base origin/develop
PERF_PG_URL=postgres://postgres:postgres@127.0.0.1:55432 scripts/perf_ab.sh /tmp/grow-perf-base . /tmp/grow-perf-results
```

The performance seed also installs the pinned 849-region staging snapshot documented in
[`perf/fixtures/region_map_index.README.md`](perf/fixtures/region_map_index.README.md),
including when reusing a database created before region benchmarks. Its checksum
is verified before use; a different existing snapshot requires recreating the
performance database. Nine region latency scenarios cover index identity/gzip and lexicon
cold/warm/304 requests. Their absolute ceilings are calibrated from five successful unchanged-head CI self-comparisons
at `fa2d9e3`, using 3× the slowest pooled side median and the rounding method above.
Existing ceilings and relative slowdown, query-count and stability gates remain unchanged.
The pinned index resolves 4,625 lexicon rows against the pinned genre exports.

Calibration runs: [1](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42410527794), [2](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42410796684), [3](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42411147145), [4](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42411513316), [5](https://github.com/BehindTheMusicTree/grow-the-music-tree-api/actions/runs/42411867398).

| Scenario | Slowest pooled side p50 (ms) | Ceiling (ms) |
| --- | ---: | ---: |
| region-map-genres (identity, cold) | 91.494 | 280 |
| region-map-genres (identity, not-modified) | 11.083 | 40 |
| region-map-genres (identity, warm) | 11.979 | 40 |
| region-map-index (gzip, cold) | 2.641 | 10 |
| region-map-index (gzip, not-modified) | 0.902 | 10 |
| region-map-index (gzip, warm) | 2.462 | 10 |
| region-map-index (identity, cold) | 4.855 | 20 |
| region-map-index (identity, not-modified) | 0.874 | 10 |
| region-map-index (identity, warm) | 4.272 | 20 |

The fixture is refreshed by hand, since an SLO needs fixed data (re-calibrate `SLO_MS` in the same PR):

```bash
for f in 1_canonical_genre_tree 1_regional_genre_tree 2_songs; do
  scp <vps>:/home/btmt-deploy/music-tree-pipelines-prod/data/gold/$f.json perf/fixtures/ && gzip -9f perf/fixtures/$f.json
done
```

## Data sources and licenses

The code in this repository is licensed under Apache 2.0. The data served by the `/v1/*` endpoints is produced by [the-music-tree-pipelines](https://github.com/BehindTheMusicTree/the-music-tree-pipelines) and keeps the license of its source:

| Source | Used for | License |
|---|---|---|
| [MusicBrainz](https://musicbrainz.org) core data | Artists, recordings, genre entities | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| [MusicBrainz](https://musicbrainz.org) supplementary data | Recording tags, from which song ↔ genre associations are derived | [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/) |
| [Wikidata](https://www.wikidata.org) | Genre taxonomy, aliases, artist image references | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| [Wikimedia Commons](https://commons.wikimedia.org) | Artist images | Per-file license; author and license travel with each image |
| [YouTube Data API](https://developers.google.com/youtube/v3) | Video candidates and playability | [YouTube API Services Terms of Service](https://developers.google.com/youtube/terms/api-services-terms-of-service) |
| [Glottolog CLDF](https://github.com/glottolog/glottolog-cldf) | Languoids for the cultural-entity backbone and region maps | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [Natural Earth](https://www.naturalearthdata.com) | Admin boundaries and map background layers | Public domain |

Data derived from MusicBrainz tags remains subject to CC BY-NC-SA 3.0: credit MusicBrainz, non-commercial use only, share-alike. See the [MusicBrainz data license](https://musicbrainz.org/doc/About/Data_License).

## License

[Apache 2.0](LICENSE)

### Import merge progress

Bulk import status endpoints retain `pending|success|failed`, `result` and `error`. Admin and pipeline callers also receive optional durable `progress` (attempt, current step, completed timings, heartbeat and bounded SQL wait diagnostics). `dataApplied=true` with a failure means the commit succeeded and post-commit processing needs inspection; do not resubmit. See [the progress contract and recovery rules](docs/operations/import-progress.md).

### Genre selection and counts

Genre catalogue reads and genre-playlist track reads accept `coverage=genre_only|genre_and_subgenres`.
Inclusive reads also accept `subgenres=canonical|regional|all`: canonical genres default to `canonical`,
regional genres default to and require `all`. Exact coverage rejects `subgenres`; Genreless rejects both parameters.
Primary paths are deduplicated; secondary parents do not contribute. Canonical coverage never crosses a regional
node on its way to another canonical genre. Regional coverage includes the selected genre and reachable regional
genres; `all` combines those selections. A regional root's `all` includes all its primary descendants.

Genre playlist summaries expose `genreOnlyTracksCount` and `genreAndSubgenresTracksCount` (`canonical`, `regional`,
`all` for canonical genres; only `all` for regional and Genreless). These count actual members of that playlist,
not the sum of other playlists' members. `catalogue` contains the same shape for all catalogue songs, including
songs without playable video. Legacy `tracksCount` follows the default membership selection; tree `songsCount`
follows the default catalogue selection. Genre detail's legacy `tracksCount` remains a catalogue count.
Artist-filtered trees have the same population separation and are not stored in the global tree cache.

Playback applies the selection before anchors, ordering and pagination. Its queue additionally respects country
availability; a global membership count does not guarantee playback in the viewer's country. Country does not
change the global summary or its cache key.

`uv run python manage.py verify_genre_membership_counts` independently checks the stored membership buckets.
`--repair` explicitly rebuilds them atomically and invalidates the tree cache. PostgreSQL source writes and repair
require the default READ COMMITTED isolation and share a transaction advisory lock; the existing tree-version row
also serializes tracked writers. Long import transactions therefore block other source writers until commit.
Reads remain unlocked. List/detail summaries add
two bounded aggregate queries, and an uncached tree adds one; playback remains four queries. This tradeoff avoids
one membership scan per genre or folding child playlists whose actual members may differ. The latest catalogue
projection is reused within a worker only while every graph/count input and requested playlist ID is identical;
actual playlist membership is always read again. Rolled-back writes cannot leave stale summary values.
