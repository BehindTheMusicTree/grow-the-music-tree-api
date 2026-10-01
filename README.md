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
- Artist, album, and Youtube-track library, with play tracking
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
| `ADMIN_GOOGLE_SUB`       | yes      | —         | Google account `sub` that gets the `admin` role; any other verified Google account is a read-only `viewer` |
| `DATABASE_URL`           | yes      | —         | Postgres connection string, parsed via `dj-database-url`                                                   |
| `DEBUG`                  | no       | `false`   |                                                                                                            |
| `ALLOWED_HOSTS`          | no       | `""`      | Comma-separated                                                                                            |
| `GIT_COMMIT`             | no       | —         | Surfaced as `commit` in `/health/`; baked into the image by the build workflow                             |
| `APP_PORT`               | no       | `8001`    | Only used by Docker Compose                                                                                |

There's no `.env.example` — Docker Compose supplies dev defaults for all of the above inline.

## API

Reads (`GET`) on `/v1/*` and `/health/` are public. Writes (`POST`/`PUT`/`PATCH`/`DELETE`) require an `Authorization: Bearer <Google ID token>` for the `ADMIN_GOOGLE_SUB` account. The `X-API-Key` header (set to `PIPELINE_API_KEY`) is for the nightly pipeline and can only write to `genres/tree/import/` and `library/youtube/songs/import/`, and read `curation/export/`; other writes with it return 403 `permission_denied`. No credentials returns 401 `authentication_required`, an invalid or expired token 401 `invalid_token`, and a verified non-admin Google account 403 `permission_denied`. `GET /v1/auth/me/` returns the caller's `{"role", "email"}` (401 when anonymous). Reference data has no owner (`user IS NULL`) and is the same for every caller; a Google sign-in creates a `User` keyed by the account's `sub`, which owns nothing yet.

| Path                          | Description                                          |
| ----------------------------- | ---------------------------------------------------- |
| `GET /health/`                | Health check (no auth)                               |
| `/v1/artists`                 | Artists                                              |
| `/v1/albums`                  | Albums                                               |
| `/v1/genres`                  | Genre criteria tree (CRUD + `{uuid}/overview/`, `tree/`, `tree/import/`, `name-conflicts/`, `name-conflicts/validate/`, `unaccepted-roots/`, `unaccepted-roots/accept/`) |
| `/v1/tags`                    | Tag criteria tree (CRUD + `{uuid}/overview/`, `tree/`, `tree/import/`) |
| `/v1/playlists`               | Playlists (CRUD + `{uuid}/tracks/`)                  |
| `/v1/manual-playlists`        | Manual playlists (CRUD + `{uuid}/tracks/`)           |
| `/v1/genre-playlists`         | Playlists derived from the genre tree (read-only, + `{uuid}/tracks/`) |
| `/v1/tag-playlists`           | Playlists derived from the tag tree (read-only, + `{uuid}/tracks/`) |
| `/v1/plays`                   | Play records                                         |
| `/v1/library/youtube`         | Youtube tracks (CRUD + `songs/import/`)           |
| `/v1/curation/lists/`         | The pipeline curation lists: `{name, keyColumns, columns, description}` (admin only) |
| `/v1/curation/{list}/entries/` | Curation entries of one list (`GET`/`POST`, `{uuid}/` `PATCH`/`DELETE`; admin only). Body `{"row": {<csv column>: value}}`, `row` keys stay snake_case |
| `/v1/curation/export/`        | Every list as CSV-ready rows keyed by list name, plain snake_case JSON (`X-API-Key` or admin) |

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
