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
  - [Environment variables](#environment-variables)
  - [API](#api)
  - [Tests](#tests)
  - [License](#license)

## Features

- Genre and tag criteria trees, with bulk tree import and export
- Playlists automatically derived from genre/tag criteria, plus manually curated playlists
- Artist, album, and Youtube-track library, with play tracking
- Single static API-key authentication — no per-user accounts, single-tenant reference dataset
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

## Environment variables

| Variable                 | Required | Default   | Notes                                                                                                      |
| ------------------------ | -------- | --------- | ---------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`             | yes      | —         | Django secret key                                                                                          |
| `SYSTEM_USERNAME`        | yes      | —         | Username for the single-tenant "system user"                                                               |
| `GROW_API_KEY`           | yes      | —         | Static API key checked against the `X-API-Key` header                                                      |
| `GOOGLE_OAUTH_CLIENT_ID` | yes      | —         | Google OAuth client ID; the expected `aud` of Google ID tokens                                             |
| `ADMIN_GOOGLE_SUB`       | yes      | —         | Google account `sub` that gets the `admin` role; any other verified Google account is a read-only `viewer` |
| `DATABASE_URL`           | yes      | —         | Postgres connection string, parsed via `dj-database-url`                                                   |
| `DEBUG`                  | no       | `false`   |                                                                                                            |
| `ALLOWED_HOSTS`          | no       | `""`      | Comma-separated                                                                                            |
| `SOURCE_COMMIT`          | no       | —         | Surfaced as `commit` in `/health/`; injected at runtime by Coolify                                         |
| `APP_PORT`               | no       | `8001`    | Only used by Docker Compose                                                                                |

There's no `.env.example` — Docker Compose supplies dev defaults for all of the above inline.

## API

Reads (`GET`) on `/v1/*` and `/health/` are public. Writes (`POST`/`PUT`/`PATCH`/`DELETE`) require an `Authorization: Bearer <Google ID token>` for the `ADMIN_GOOGLE_SUB` account. The `X-API-Key` header (set to `GROW_API_KEY`) is for the nightly pipeline and can only write to `genres/tree/import/` and `library/youtube/songs/import/`; other writes with it return 403 `permission_denied`. No credentials returns 401 `authentication_required`, an invalid or expired token 401 `invalid_token`, and a verified non-admin Google account 403 `permission_denied`. `GET /v1/auth/me/` returns the caller's `{"role", "email"}` (401 when anonymous). The service is single-tenant: every principal acts on the one "system user", and every record belongs to it.

| Path                          | Description                                          |
| ----------------------------- | ---------------------------------------------------- |
| `GET /health/`                | Health check (no auth)                               |
| `/v1/artists`                 | Artists                                              |
| `/v1/albums`                  | Albums                                               |
| `/v1/genres`                  | Genre criteria tree (CRUD + `tree/`, `tree/import/`, `tree/load-seed/`) |
| `/v1/tags`                    | Tag criteria tree (CRUD + `tree/`, `tree/import/`)   |
| `/v1/playlists`               | Playlists                                            |
| `/v1/manual-playlists`        | Manual playlists                                     |
| `/v1/genre-playlists`         | Playlists derived from the genre tree (read-only)    |
| `/v1/tag-playlists`           | Playlists derived from the tag tree (read-only)      |
| `/v1/plays`                   | Play records                                         |
| `/v1/library/youtube`         | Youtube tracks (CRUD + `songs/load-seed/`)        |

`POST tree/load-seed` on `/v1/genres` (re)seeds the system user's seed genre tree and seed songs; `POST songs/load-seed` on `/v1/library/youtube` seeds just the seed songs.

Full request/response details per resource are documented in [`docs/api/`](docs/api/).

A [Bruno](https://www.usebruno.com/) collection for manual testing is at [`bruno/Track/`](bruno/Track/) — open it in the Bruno app, select the `local` environment, and set the `API_KEY` secret to your `GROW_API_KEY`.

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

## License

[Apache 2.0](LICENSE)
