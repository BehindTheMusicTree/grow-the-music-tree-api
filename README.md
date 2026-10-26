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

Replaces the Docker Compose `db` with the latest prod backup (Coolify's daily `pg_dump` to Cloudflare R2), then restarts `api`/`worker`, which apply the current branch's migrations. Includes admin curation that the pipeline Gold exports in `perf/fixtures/` lack. The dump holds only the public canonical dataset, so it is safe on a laptop. Requires [rclone](https://rclone.org/) and a config with an `[r2]` remote (`type = s3`, `provider = Cloudflare`, `endpoint = https://<account-id>.r2.cloudflarestorage.com`) using a **read-only** R2 token scoped to the backup bucket, not the VPS's read/write one. Token setup: infrastructure's [`docs/guides/cloudflare-r2-backup-setup.md` § 5](https://github.com/BehindTheMusicTree/infrastructure/blob/main/docs/guides/cloudflare-r2-backup-setup.md#5-local-dev-read-only-token-prod-db-restore).

## Environment variables

| Variable                 | Required | Default   | Notes                                                                                                      |
| ------------------------ | -------- | --------- | ---------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`             | yes      | —         | Django secret key                                                                                          |
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

Reads (`GET`) on `/v1/*` and `/health/` are public. Writes (`POST`/`PUT`/`PATCH`/`DELETE`) require an `Authorization: Bearer <Google ID token>` for the `ADMIN_GOOGLE_SUB` account. The `X-API-Key` header (set to `PIPELINE_API_KEY`) is for the nightly pipeline and can only write to `genres/tree/import/`, `library/songs/songs/import-runs/` (legacy alias `library/youtube/songs/import-runs/`) and `artists/import-runs/` (create, part upload, commit), `pipeline/imports/unresolved-genre-tags/`, `curation/wikidata-resolutions/`, `curation/wikidata-items/`, `pipeline/runs/` (`full` only), `pipeline/runs/claim/` and `pipeline/runs/{uuid}/`, and read `curation/export/` and `pipeline/runs/latest/`; other writes with it return 403 `permission_denied`. No credentials returns 401 `authentication_required`, an invalid or expired token 401 `invalid_token`, and a verified non-admin Google account 403 `permission_denied`. `GET /v1/auth/me/` returns the caller's `{"role", "email"}` (401 when anonymous). Reference data has no owner (`user IS NULL`) and is the same for every caller; a Google sign-in creates a `User` keyed by the account's `sub`, which owns nothing yet.

| Path                          | Description                                          |
| ----------------------------- | ---------------------------------------------------- |
| `GET /health/`                | Health check (no auth)                               |
| `/v1/albums`                  | Albums                                               |
| `/v1/artists`                 | Artists (list, detail with MusicBrainz details, members, links and release-group albums, + `import-runs/`) |
| `/v1/genres`                  | Genre criteria tree (CRUD + `{uuid}/overview/`, `{uuid}/exclude/` (body `{"category": "theme"\|"technique"\|"out_of_scope"\|"duplicate"}`), `tree/`, `tree/import/`, `name-conflicts/`, `name-conflicts/validate/`, `unaccepted-roots/`, `unaccepted-roots/accept/`) |
| `/v1/tags`                    | Tag criteria tree (CRUD + `{uuid}/overview/`, `tree/`, `tree/import/`) |
| `/v1/playlists`               | Playlists (CRUD + `{uuid}/tracks/`; on every playlist route, `tracks/?from=<track uuid>` starts the list at that track in play order, 404 if it is not in the playlist, 400 if not a UUID) |
| `/v1/manual-playlists`        | Manual playlists (CRUD + `{uuid}/tracks/`)           |
| `/v1/genre-playlists`         | Playlists derived from the genre tree (read-only, + `{uuid}/tracks/`) |
| `/v1/tag-playlists`           | Playlists derived from the tag tree (read-only, + `{uuid}/tracks/`) |
| `/v1/plays`                   | Play records                                         |
| `/v1/library/songs`      | Songs (CRUD + `songs/import-runs/`, `?genre=`, `?artist=`, `?playable=`, `?from=<uuid>`, `?ordering=title\|-title\|albumYear\|-albumYear`); legacy aliases `/v1/library/recordings` and `/v1/library/youtube` |
| `/v1/curation/lists/`         | The pipeline curation lists: `{name, keyColumns, columns, description}` (admin only) |
| `/v1/curation/{list}/entries/` | Curation entries of one list (`GET`/`POST`, `{uuid}/` `PATCH`/`DELETE`; admin only). Body `{"row": {<csv column>: value}}`, `row` keys stay snake_case |
| `/v1/curation/export/`        | Every list as CSV-ready rows keyed by list name, plus `exported_on` (ISO 8601, the export's instant), plain snake_case JSON (`X-API-Key` or admin) |
| `/v1/curation/wikidata-resolutions/` | `POST {remaps: [{list, key, column, from, to}], review: [{list, key, column, itemId, reason: redirect_conflict\|missing\|not_in_tree, target?, evidence?}]}`, the pipeline's Wikidata resolution of curation item ids (`X-API-Key` or admin). Each remap rewrites the redirected id `from` to `to` in the `column` of entry `key` of `list`, recording history with a null actor; a remap clashing with another entry becomes a `redirect_conflict` review item, one whose entry or `from` id is gone is skipped. `evidence` is the Wikidata facts seen at detection, unknown keys rejected: `{label?, modified?, instanceOf?, subclassOf?: [{id, label}], hasIndigenousTo?, conflictList?}`. Replaces every review item. Returns `{remappedCount, reviewCount}` |
| `/v1/curation/wikidata-items/` | `POST {items: [{id, label}]}`, the pipeline's catalog of every Wikidata item it knows (pruned ones and `LOCAL:` ones included), `X-API-Key` or admin. Replaces the whole catalog; names the item ids that aren't in the canonical tree. Returns `{itemCount}` |
| `/v1/curation/items/` | `GET ?q=` (admin) searches item ids by name or id across the canonical tree, the catalog and pending additions: `{results: [{id, label}]}`, 400 without `q` |
| `/v1/curation/review/`        | `GET` the last report's review items, the ids the pipeline dropped: `[{list, key, column, itemId, reason, target, evidence, reportedOn}]` (`evidence` null when not reported, always null on API-side remap conflicts) (admin only) |
| `/v1/pipeline/runs/`          | `GET` the run requests, newest first, paginated (admin only). `POST {kind: curation\|full\|sync}` queues a pipeline run: a rebuild from current curation, a full ingestion, or a replay of the last complete Gold output into grow. An admin's request has `trigger: manual` and `requestedBy` their email; the `X-API-Key`'s (the nightly) has `trigger: scheduled`, `requestedBy: null`, and may only request `full` (400 otherwise, so `sync` is admin-only). 409 if any run is queued or running, 400 for `curation` with no edit pending. A request is `{uuid, kind, trigger, requestedBy, status, stage, stageCurrent, stageTotal, error, cancelRequested, requestedOn, startedOn, heartbeatOn, finishedOn}`, `status` `queued\|running\|succeeded\|failed\|superseded\|cancelled\|expired`, `stage` `fetching_rules\|ingesting_musicbrainz\|ingesting_wikidata\|building_songs\|building_genres\|matching_songs\|importing_tree\|uploading_songs\|merging_songs\|uploading_artists\|merging_artists` |
| `/v1/pipeline/runs/latest/`   | `GET` the newest run request, 204 if none (`X-API-Key` or admin) |
| `/v1/pipeline/runs/claim/`    | `POST` starts the oldest queued request (`running`), or marks a `curation` one `superseded` if no edit is pending anymore; 204 if none queued (`X-API-Key` or admin) |
| `/v1/pipeline/runs/{uuid}/`   | `PATCH {stage?, stageCurrent?, stageTotal?, status?: succeeded\|failed\|cancelled, error?}` on the running request, an empty body being a heartbeat; a new `stage` resets the progress counts, a `status` sets `finishedOn`; `cancelRequested: true` in the response means stop the run and report `cancelled`; 409 if not running (`X-API-Key` or admin). A running request with no PATCH for 30 min becomes `expired` |
| `/v1/pipeline/runs/{uuid}/cancel/` | `POST` cancels a queued request, or sets `cancelRequested` on a running one; 409 if neither (admin only) |
| `/v1/pipeline/imports/`       | Pipeline import history, newest first, paginated, `?kind=canonical_tree\|regional_tree\|songs\|unresolved_genre_tags`: `{kind, importedOn, count, skippedCount}` (admin only). Recorded on every `X-API-Key` tree or songs import (`skippedCount`: songs with no matching genre), not on admin imports |
| `/v1/pipeline/imports/latest/` | Newest run per kind: `{canonicalTree, regionalTree, songs, unresolvedGenreTags}`, each a run or `null` (admin only) |
| `/v1/pipeline/imports/unresolved-genre-tags/` | `POST {"unresolvedGenreTagCount": n}`: records the pipeline's count of song genre tags it couldn't match to a genre, returns the run (`X-API-Key` or admin) |

An admin edit of a wikidata-backed genre also upserts the curation rule that makes the pipeline reproduce it, with reason `grow admin edit by <pseudo>`: a rename goes to `label_overrides`, a canonical reparent to `main_parent` (`exclude_other_parents`), a root acceptance to `accepted_canonical_roots`, and an exclusion to `<category>_genres`. Edits no list expresses return 400: a reparent to a root, under an app-created genre, or in the regional tree. Genres without a `wikidataId` are app-created, absent from the pipeline's output, so their edits only lock the row.

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

Two gates keep list and detail endpoints fast. Changing a budget or an SLO is a deliberate, reviewed diff, not a way to make CI pass.

- **Query budgets** (`tests/integration/perf/test_query_budgets.py`, part of `uv run pytest`): each endpoint must run a fixed number of queries whatever the number of rows, and no more than its `BUDGETS` entry.
- **Latency SLOs** (`perf/`, CI job `Perf`): median latency per endpoint on Postgres (p95 is printed too), seeded with a pinned snapshot of the prod pipeline's Gold exports (`perf/fixtures/`), imported through the same endpoints and in the same order as the nightly sync.

```bash
docker run -d --name grow-perf-pg -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:55432:5432 postgres:16-alpine
PERF_DATABASE_URL=postgres://postgres:postgres@127.0.0.1:55432/postgres uv run pytest perf --no-cov -s --ds=perf.settings --reuse-db
```

The fixture is refreshed by hand, since an SLO needs fixed data (re-calibrate `SLO_MS` in the same PR):

```bash
for f in 1_canonical_genre_tree 1_regional_genre_tree 2_songs; do
  scp <vps>:/home/btmt-deploy/music-tree-pipelines-prod/data/gold/$f.json perf/fixtures/ && gzip -9f perf/fixtures/$f.json
done
```

## License

[Apache 2.0](LICENSE)
