# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`grow-the-music-tree-api`: the reference genre/tag/tree service backing `grow-the-music-tree-frontend`. Single-tenant (one "system user", no per-user accounts), API-key-authenticated Django/DRF app. Depends on two shared internal packages pulled via git in `pyproject.toml`:

- [`the-music-tree-genre-kit`](https://github.com/BehindTheMusicTree/the-music-tree-genre-kit) — shared genre/tag/criteria/tree logic, plus the shared `Track` base model (Django MTI).
- [`the-music-tree-api-kit`](https://github.com/BehindTheMusicTree/the-music-tree-api-kit) — shared DRF error handling, field types, and swappable-model FK plumbing (`PrivateForeignKey`, `PrivateOneToOneField`, etc.).

`hear-the-music-tree-api` is a sibling app consuming the same two kits — when changing shared kit behavior, check whether hear needs the equivalent change.

## Setup

```bash
docker compose up
```

Starts Postgres + the API with dev defaults baked into `docker-compose.yml` — no env file needed. Serves on `http://localhost:8001`, health check at `GET /health/`.

Local (uv + external Postgres) alternative:

```bash
uv sync
# set SECRET_KEY, SYSTEM_USERNAME, GROW_API_KEY, DATABASE_URL (see README.md)
uv run manage.py migrate
uv run manage.py runserver
```

## Commands

- **Tests:** `uv run pytest` — in-memory SQLite, no env vars needed (`DJANGO_SETTINGS_MODULE=tests.settings` is set via `pyproject.toml`'s `[tool.pytest.ini_options]`). Coverage gate: `--cov-fail-under=85`.
- **Lint:** `uv run ruff check .` / `uv run ruff format --check .` (rules vendored from `baselines/ruff.toml`, itself vendored from genre-kit, itself from hear).
- **Types:** `uv run mypy grow` — imports `grow/settings.py` directly (not `tests.settings`), so it needs real env vars even though it's read-only: `SECRET_KEY`, `SYSTEM_USERNAME`, `GROW_API_KEY`, `PROTOTYPE_USERNAME`, `GROW_PROTOTYPE_API_KEY`, `DATABASE_URL`, `APP_VERSION` all dummy values are fine, e.g.:
  ```bash
  SECRET_KEY=x SYSTEM_USERNAME=x GROW_API_KEY=x PROTOTYPE_USERNAME=x GROW_PROTOTYPE_API_KEY=x DATABASE_URL=sqlite:///:memory: APP_VERSION=0.0.0 uv run mypy grow
  ```
- **Migration check:** `DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=. uv run django-admin makemigrations grow --check --dry-run` — must produce zero output; this is what CI's `Migration check` job runs.
- These four map 1:1 to CI (`.github/workflows/test.yml` jobs `Lint`, `Migration check`, `Pytest`) — run all of them before opening a PR.

## Architecture

**Swappable-model settings** (`grow/settings.py`), resolved by the kits exactly like Django resolves `AUTH_USER_MODEL`: `CRITERIA_MODEL`, `TRACK_MODEL`, `ARTIST_MODEL`, `ALBUM_MODEL`. **`tests/settings.py` is a separate, independently-maintained settings module** (used for `DJANGO_SETTINGS_MODULE=tests.settings` in pytest, mypy's stub config, and CI's migration check) — it does NOT inherit from `grow/settings.py`. Any new setting added to one must be manually mirrored into the other, or you get collection-time `AttributeError`s that look unrelated to your actual change.

**Track model is Django MTI onto a kit-owned parent, with a single concrete child**: `the_music_tree_genre_kit.Track` is the shared base (title, artists, album, track_number, genre, rating, language, archived, play_count — no `playlists` field by design, see below). `YoutubeTrack` (`grow/model/youtube_track/YoutubeTrack.py`) is grow's only concrete `parent_link=True` MTI child (the earlier `UploadedTrack` child was retired), so `TRACK_MODEL` points directly at `"grow.YoutubeTrack"`, not at the kit's shared parent. `YoutubeTrack` defines its own `__str__`, `simple_str()`, and `playlists_with_positions` — there's no `resolve_concrete()` downcast machinery since there's only one concrete type to resolve to.

**The kit's `Track` deliberately has no `playlists` M2M field** (avoids a migration-dependency cycle across app boundaries — see the kit's own `Track.py` docstring). Playlist membership is reconstructed at the app level via `YoutubeTrack.playlists_with_positions`, which queries `TrackPlaylistRel.objects.filter(user=self.user, track=self)` directly.

**`grow/apps.py`'s `GrowConfig.ready()`** imports `grow.model.user.signals`, which bootstraps a criteria-less `CriteriaPlaylist` row per new user — see `CHANGELOG.md` for the bug this fixes. That's the only thing it wires up.

**Custom DRF exception handler** (`the_music_tree_api_kit.view.error.exception_handler.custom_exception_handler`, wired via `REST_FRAMEWORK["EXCEPTION_HANDLER"]`) always converts exceptions to JSON under pytest (`"pytest" in sys.argv[0]`), regardless of `DEBUG`. Unregistered exception types fall through to a generic `{"message": "An internal error occurred"}` response with **no logging of the underlying exception** — if a test gets an unexplained 500, don't trust `caplog`; temporarily instrument the installed package file directly (back it up first) to print the traceback, then revert it before committing anything.

**Prototype-user seeding (`seed_prototype_tree`)**: `grow/management/commands/seed_prototype_tree.py` (re)seeds the read-only prototype user's genre tree from the bundled `grow/data/prototype_genre_tree.json` and its tracks from a **required** `--songs-file <path>` JSON (list of `{title, artist, youtube_video_id, genre_name}` objects; fails fast if omitted — there is no bundled fallback). That file is produced externally by `the-music-tree-pipelines` (`musicbrainz` pipeline's Silver `song_example` step + `scripts/export_song_example_json.py`), not committed to this repo. This command is **not wired into any deploy hook or CI job** — a `develop`/`main` push never re-runs it, so it must be run by hand (e.g. `docker exec` into the running `gtmt-api` container) whenever the upstream song dataset changes. See `infrastructure` repo's `diag-vps` command doc for the VPS container-resolution steps.

## Repo conventions (from `CONTRIBUTING.md`)

- **Branching:** `main` (prod, Coolify auto-deploy) and `develop` (staging, Coolify auto-deploy) are both protected — no direct commits, ever. Topic branches: `feature/<name>`, `fix/<name>`, `chore/<name>`, branched from `develop`, merged back into `develop` via PR. No `main`-targeting flow exists yet.
- **Commits and PR titles:** `<type>(<scope>): <summary>` — `feat`, `fix`, `refactor`, `docs`, `chore`, `test`, `style`, `perf`, `ci`. Imperative mood, under ~70 chars.
- **Before opening a PR:** all four commands in "Commands" above pass; new features/fixes have tests; `CHANGELOG.md` updated under `[Unreleased]`; `README.md` updated if endpoints/env vars/setup changed; no secrets.
- Hand-author (don't trust autogeneration for) any migration that changes MTI `bases=` — `SeparateDatabaseAndState.database_operations` never sees `state_operations`' `bases=` changes, so a naive `AlterField`/autogenerated migration can silently inject a phantom `*_ptr_id` column. See `grow/migrations/0006_move_track_to_genre_kit.py` for the `schema_editor.alter_field()` workaround.
