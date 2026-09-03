---
name: launch
description: Use this skill when asked to run, start, or dev-serve grow-the-music-tree-api, or to confirm a change works against a real running instance. Covers the Docker Compose stack (Postgres + Django API).
---

# Launch grow-the-music-tree-api

Docker Compose is the only supported dev path — no env file is required, dev
defaults are baked into `docker-compose.yml`.

## Start

```bash
docker compose up
```

This starts:
- **`db`** — Postgres 16.4 on host port `5433`
- **`api`** — Django, via `docker-compose.override.yml`'s command: waits for
  Postgres, runs `python3 manage.py migrate`, then
  `python3 manage.py runserver 0.0.0.0:${APP_PORT:-8001}` with the repo
  mounted for live reload

The API is served on `http://localhost:8001`.

## Verify

```bash
curl http://localhost:8001/health/
```

## Notes

- Override env vars (`APP_PORT`, `SECRET_KEY`, `DATABASE_URL`, etc.) via a
  shell export or a local `.env` picked up by Docker Compose — none is
  required for a plain dev run.
- To run without Docker (e.g. for faster iteration), install deps with `uv
  sync` and run `python3 manage.py migrate && python3 manage.py runserver`
  against a locally reachable Postgres — not the primary supported path, see
  README.md for details.
