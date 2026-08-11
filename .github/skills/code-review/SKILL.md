---
name: code-review
description: Repository-specific context for reviewing pull requests in grow-the-music-tree-api, the reference genre/tag/tree service for grow-the-music-tree-frontend.
license: MIT
---

`grow-the-music-tree-api` is a deployable Django/DRF service (uv, PEP 621), the Django app label is `grow` (not `api`) — flag any new code that assumes `api` as the label (e.g. in `apps.get_model()` calls or migration app references). It owns what used to be `hear-the-music-tree-api`'s `reference/*` namespace: a single-tenant, read-mostly canonical genre/tag/tree dataset. There is no per-user scoping and no "system user" concept here — that trick existed only in hear-api to fake single-tenancy inside a multi-tenant service.

## Scope boundary

This repo depends on two shared packages and must not reimplement what they already provide:
- `the-music-tree-api-kit` — generic, non-genre HTTP infra (`BaseModel`, `PrivateModel`, `AppModelViewSet`, `AppFilterSet`, `ErrorResponse`, pagination, etc.).
- `the-music-tree-genre-kit` — genre/tag/criteria/tree domain logic (`AbstractCriteria`, `AbstractCriteriaManager`, `GenreManager`/`TagManager`, criteria serializers).

Flag any PR that:
- Reimplements a class that already exists in one of these packages instead of importing/subclassing it.
- Adds new generic (non-genre) infra directly in `grow/` instead of proposing it for api-kit.
- Adds new genre/tag/criteria/tree logic directly in `grow/` instead of proposing it for genre-kit — this repo's own model code should be thin concrete subclasses (`Criteria(AbstractCriteria)`, `Genre`/`Tag` proxies) plus hook overrides for its own playlist-maintenance needs, not fresh tree-structure logic.
- Domain code that is genuinely local to grow only (artist/album/playlist/manual-playlist/play/uploaded-track — deliberately *not* shared with hear-api) is expected and fine here.

## Config / fail-fast pattern

`grow/settings.py` reads `SECRET_KEY`/`DATABASE_URL` via `os.environ[...]` with no defaults — this is intentional fail-fast behavior, not an oversight. Don't suggest adding fallback defaults for these two required env vars. `DEBUG`/`ALLOWED_HOSTS` deliberately do use `os.environ.get(...)` with defaults (`"false"`/empty) since they're optional in local/dev setups — don't flag those as violating the fail-fast pattern.

## Migrations

No migration files are ever copied in from hear-api or the shared packages — this service generates its own independent migration history against the shared abstract base classes. Flag any PR that changes a model field without a corresponding migration, or that hand-edits a migration file instead of regenerating it via `makemigrations`.

## Cross-repo dependency pins

`pyproject.toml` pins `the-music-tree-api-kit` and `the-music-tree-genre-kit` via `git+https://...@<tag>`. When reviewing a PR that bumps either pin, confirm it points at a real tag on that package's `main` (not a feature branch), that the corresponding change has already merged and gone green in its own CI, and that `uv.lock` was regenerated in the same commit — a stale lockfile after a pin bump is easy to miss in review. Also watch for git-ref conflicts: if two dependencies-of-dependencies pin the same shared package to different refs, `uv lock` fails even when one ref is a strict ancestor of the other (uv does not do content-based dedup across git refs).

## Style and tooling

- Ruff config is vendored from `hear-the-music-tree-api/baselines/ruff.toml` (`line-length = 120`) via `extend` in `pyproject.toml` — don't suggest reformatting to a different line length or diverging from the vendored baseline.
- `mypy` runs with several error codes disabled repo-wide because of Django's dynamic model/manager typing (see `[tool.mypy] disable_error_code`) — don't ask for stricter local `# type: ignore` cleanup that fights this.
- No `print()`/debug leftovers.
