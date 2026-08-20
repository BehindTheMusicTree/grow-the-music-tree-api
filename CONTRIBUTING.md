# Contributing Guidelines

Thank you for your interest in contributing! This project is currently maintained by a solo developer, but contributions, suggestions, and improvements are welcome.

## Table of Contents

- [Contributors vs Maintainers](#contributors-vs-maintainers)
- [Development Workflow](#development-workflow)
  - [1. Environment Setup](#1-environment-setup)
  - [2. Branching](#2-branching)
  - [3. Testing](#3-testing)
  - [4. Committing](#4-committing)
  - [5. Pull Request Process](#5-pull-request-process)
- [License & Attribution](#license--attribution)

## Contributors vs Maintainers

**Contributors** can submit bug reports and feature requests via GitHub Issues, propose changes via Pull Requests, improve documentation, and participate in discussions.

**Maintainers** review and merge Pull Requests, manage repository configuration, and are responsible for project direction.

**Important:** No direct commits to `main` or `develop` — all changes, including from maintainers, go through Pull Requests.

Currently this project has a solo maintainer, but the role may expand as the project grows.

## Development Workflow

### 1. Environment Setup

#### Prerequisites

- Python 3.14
- [uv](https://docs.astral.sh/uv/)
- Docker + Docker Compose (for Postgres, or to run the full stack containerized)

#### Installation

```bash
git clone https://github.com/BehindTheMusicTree/grow-the-music-tree-api.git
cd grow-the-music-tree-api
docker compose up
```

This starts Postgres and the API with dev-friendly defaults already set in `docker-compose.yml` — no env file needed. See [README.md](README.md) for the local (uv + external Postgres) alternative and the full environment variable reference.

### 2. Branching

- **`main`** — production. Coolify auto-deploys to prod on every push. No direct commits — only merges from PRs.
- **`develop`** — staging integration branch. Coolify auto-deploys to staging on every push. No direct commits — only merges from PRs.
- **`feature/<name>`** — new features, branched from `develop`, merged back into `develop` via PR.
- **`fix/<name>`** — bug fixes, branched from `develop`, merged back into `develop` via PR.
- **`chore/<name>`** — maintenance, tooling, CI/CD, dependency updates, branched from `develop`, merged back into `develop` via PR.

There is no automated branch-name enforcement (no `branch-protection.yml` workflow) — these prefixes are a convention, not a CI-checked rule.

This repo has no `release/*` or `hotfix/*` flow yet and no tagged releases — `main`/`develop` deploy directly via Coolify on every push, so there's nothing to formally release. Add that process if/when it's actually needed.

### 3. Testing

```bash
uv run pytest
```

Tests run against an in-memory SQLite database and need no environment variables. Also run before opening a PR:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy grow
uv run django-admin makemigrations grow --check --dry-run
```

These are the same checks CI runs (`.github/workflows/test.yml`, jobs `Lint`, `Migration check`, `Pytest`) on every PR to `main` or `develop`.

### 4. Committing

Structured commit format inspired by [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <summary>
```

Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`, `style`, `perf`, `ci`.

Examples:

- `feat(track): add batch upload endpoint`
- `fix(genre): handle empty genre nodes`
- `chore: update dependencies`

Use imperative mood, keep the summary under ~70 characters, include issue IDs when applicable.

### 5. Pull Request Process

Before opening a PR:

- ✅ `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy grow`, and `uv run pytest` all pass
- ✅ New features/bug fixes have corresponding tests
- ✅ `CHANGELOG.md` updated under `[Unreleased]`
- ✅ `README.md` updated if endpoints, env vars, or setup steps changed
- ✅ No secrets, large files, or accidental commits
- ✅ Branch targets `develop` (features/fixes/chores) — this repo has no `main`-targeting flow yet

**PR title** follows the same `<type>(<scope>): <summary>` format as commits, e.g. `feat(track): add batch upload endpoint`.

## License & Attribution

All contributions are made under the project's Apache License 2.0. You retain authorship of your code; the project retains redistribution rights under the same license. See the [LICENSE](LICENSE) file for details.
