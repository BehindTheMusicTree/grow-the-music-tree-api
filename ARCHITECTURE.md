# Architecture

This is a from-scratch walkthrough of how the pieces fit together — the domain model, the two kit dependencies, and a full request lifecycle. `CLAUDE.md` is the Claude-facing operational doc (commands, gotchas, conventions); `README.md` is the setup/API-consumer doc (env vars, routes, features). This file is for understanding the system's shape, not for either of those jobs — where a detail already lives correctly in one of them, this file links to it instead of restating it.

## System summary

`grow` is a single-tenant Django/DRF service backing the genre/tag/tree domain for `grow-the-music-tree-frontend`. "Single-tenant" here means exactly two `User` rows ever exist: a system user (full read/write, `GROW_API_KEY`) and a read-only prototype user (`GROW_PROTOTYPE_API_KEY`, writes rejected with 403). There are no per-user accounts, no signup flow, no custom user model — tenancy is a settings value compared against a request header.

## Dependency architecture

Two internal git-pulled packages sit underneath `grow`, and they're pinned differently — worth knowing before you go looking for one in `pyproject.toml` and can't find it:

- **`the-music-tree-genre-kit`** (currently `v0.9.0`) — the **direct** dependency, listed in `pyproject.toml`. Provides the shared `Track`/`Playlist` MTI parent models, `AbstractCriteria`/`AbstractCriteriaManager`, `TrackMixin`, the example-tree/example-song import mixins (`GenreExampleTreeMixin`, `SongExampleTreeMixin`), and the shared `DATA_DIR` fixture directory.
- **`the-music-tree-api-kit`** (currently `v0.4.0`) — **transitive only**. It's a dependency of genre-kit, not of `grow` — pinned in `uv.lock`, not in `pyproject.toml`. Provides `BaseModel`/`BaseManager` (the `.save()` pipeline every model ultimately runs through), `AppModelViewSet` (the real CRUD/pagination/filtering scaffolding `GrowModelViewSet` sits on), the FK/serializer field types (`PrivateForeignKey`, `PrivateOneToOneField`, `PrivateUuidField`, `AppCharField`), the exception handler, and middleware (`CamelToSnakeMiddleware`, `HostValidationMiddleware`).

Sibling app `hear-the-music-tree-api` consumes both kits too — a kit-facing change here may need the equivalent change there (see `CLAUDE.md`).

## Directory layout

| Path | Purpose |
|---|---|
| `grow/model/` | Domain models, one subpackage per model, Django-file-per-class style (`Model.py`, `ModelManager.py`, `Fields.py`). |
| `grow/view/permission/` | Custom DRF permission classes (`AuthenticatedForWritesReturn401`, `ReadOnlyForPrototypeUser`). |
| `grow/view/viewset/` | Per-model viewsets plus the `GrowModelViewSet` base. |
| `grow/serializer/model/<model>/{input,output}/` | Per-model serializers. |
| `grow/filtering/` | django-filter `FilterSet` subclasses and custom filter field classes. |
| `grow/authentication/` | `ApiKeyAuthentication.py` — the two-key auth backend. |
| `grow/migrations/` | Standard Django migrations; `0006`–`0011` document the genre-kit extraction (moving `Track`/`Playlist`/`TrackPlaylistRel` ownership into the kit); `0003`/`0013` seed the system/prototype users. |
| `grow/management/commands/` | `seed_prototype_tree.py` — the only management command in the app. |
| `grow/data/` | `prototype_genre_tree.json` — the prototype-user genre-tree fixture (`seed_prototype_tree`'s tracks come from a required `--songs-file` path instead, not committed here; the generic example-tree fixture used by `tree/load-example` lives in the kit's own `DATA_DIR`). |

Known cleanup item, not fixed here: `grow/serializer/model/uploaded_track/`, `grow/filtering/set/uploaded_track/`, and `grow/view/viewset/model/uploaded_track/` still exist as empty directories (only stale `.pyc` cache remnants inside, no `.py` source) — leftover from the `UploadedTrack` model's removal. Safe to `git clean`/delete; not part of live structure.

## Domain model: the Criteria tree ⇄ Playlist mirror

This is the least obvious part of the system and worth understanding before touching anything genre/tag-related.

`Criteria` is the one real table. `Genre` and `Tag` (`grow/model/criteria/children/genre/Genre.py`, `.../tag/Tag.py`) are `proxy=True` subclasses of `Criteria` — not separate tables — distinguished only by a fixed `CriteriaType` that each one's overridden `save()` forces onto every row it creates (`CriteriaTypePks.GENRE` / `CriteriaTypePks.TAG`). A `Criteria` row's "type" is data, not schema.

Every `Criteria` node has a 1:1 shadow `CriteriaPlaylist`, kept in sync automatically by `CriteriaManager` (`grow/model/criteria/CriteriaManager.py`):
- `_on_created` creates the matching `CriteriaPlaylist` the moment a `Criteria` row is created.
- `_on_parent_changed` re-parents the shadow playlist, recomputes ascendant track membership (`update_ascendants_tracks`), and propagates root changes down to descendants.

`CriteriaPlaylist` (`grow/model/playlist/children/criteria/CriteriaPlaylist.py`) is itself MTI onto the kit's `Playlist` (`playlist = PrivateOneToOneField(KitPlaylist, parent_link=True, ...)`), mixed with the kit's `AbstractCriteriaPlaylist`. At module load time it wires manual dependency injection — `CriteriaPlaylistManager.track_playlist_rel_model = TrackPlaylistRel`, `.track_model = Track`, `TrackManager.criteria_playlist_model = CriteriaPlaylist` — specifically to avoid a circular import across the kit/app boundary. **Don't "clean this up"** by moving it into `__init__` methods or removing it as dead-looking code; it's load-bearing wiring, not leftover scaffolding.

`GenrePlaylist`/`TagPlaylist` (`grow/model/playlist/children/criteria/genre/`, `.../tag/`) are further specializations of `CriteriaPlaylist` backing the read-only genre/tag playlist endpoints.

Net picture: one self-referential `Criteria` tree (parent/children + `CriteriaLineageRel` for precomputed ascendant/descendant lookups), `type` discriminating Genre vs Tag, with an auto-maintained shadow playlist per node that tracks attach to and get queried through.

## Track model

Single concrete track type: `YoutubeTrack(KitTrack)` (`grow/model/youtube_track/YoutubeTrack.py`), MTI onto the kit's `Track` via `track = PrivateOneToOneField(KitTrack, on_delete=models.CASCADE, parent_link=True, ...)`. `settings.TRACK_MODEL = "grow.YoutubeTrack"` points directly at the concrete child — see `CLAUDE.md`'s Architecture section for why (no downcasting/`resolve_concrete` needed since there's only one child).

The kit's `Track` deliberately has no `playlists` M2M field. `YoutubeTrack.playlists_with_positions` reconstructs membership at query time via `TrackPlaylistRel.objects.filter(user=self.user, track=self)`.

## Auth & permission layering

Full chain for a single authenticated request:

1. **`ApiKeyAuthentication`** (`grow/authentication/ApiKeyAuthentication.py`) — reads `X-API-Key`, flat two-branch check against two static settings values (plain string equality, no hashing/rotation): `GROW_API_KEY` → system user, `GROW_PROTOTYPE_API_KEY` → prototype user. Anything else → unauthenticated.
2. **`GrowModelViewSet`** (`grow/view/viewset/GrowModelViewSet.py`) sets `permission_classes = [AuthenticatedForWritesReturn401, ReadOnlyForPrototypeUser]`, DRF-ANDed:
   - `AuthenticatedForWritesReturn401` — allows unauthenticated `SAFE_METHODS`; on writes, raises `NotAuthenticated` (401) instead of DRF's default 403 if the request isn't authenticated at all.
   - `ReadOnlyForPrototypeUser` — allows all `SAFE_METHODS`; on writes, raises `PermissionDenied` (403) if `request.user.username == settings.PROTOTYPE_USERNAME`.
3. Every concrete viewset inherits `GrowModelViewSet` directly, with no per-viewset override — this permission composition applies uniformly across the whole API surface.

"Tenancy" is entirely settings + username string comparison — there's no custom user model and no `is_prototype` flag on `User`.

## Request lifecycle, traced through Genre

`Genre` (proxy of `Criteria`) → `GenreManager` (`grow/model/criteria/children/genre/GenreManager.py`, extends `CriteriaManager`, filters `type_id=CriteriaTypePks.GENRE`, overrides `_get_direct_tracks`) → serializers in `grow/serializer/model/criteria/` — there are no genre-specific serializer files; Genre reuses the shared `Criteria*Serializer` family (`CriteriaDetailedSerializer`, `CriteriaSimpleSerializer`, `CriteriaPostSerializer`, `CriteriaPutSerializer`) → `CriteriaViewSet` (`grow/view/viewset/model/criteria/CriteriaViewSet.py`) wires `model_class`/`filterset_class`/all four serializer classes and implements `create`/`destroy`/`list`/`retrieve`/`update` → `GenreViewSet` (`grow/view/viewset/model/criteria/children/genre/GenreViewSet.py`) subclasses `GenreExampleTreeMixin[Genre]` + `CriteriaViewSet`, adding `POST tree/load-example` → `grow/urls.py` registers it: `router.register(r"genres", GenreViewSet, basename="genre")`.

One thing this trace surfaces that's easy to miss: `AppModelViewSet` (api-kit) defaults **every** action (`list`/`create`/`retrieve`/`update`/`destroy`) to `MethodNotAllowed`. A concrete viewset gets nothing for free — `CriteriaViewSet` has to explicitly implement each one it wants to expose. If a new viewset silently 405s on an action you expected to work, this is why.

`CriteriaDetailedSerializer` (`grow/serializer/model/criteria/output/detailed.py`) is a good example of the composition style used throughout: it nests `CriteriaMinimumSerializer` (parent/root/children), `CriteriaLineageRelWithout{Ascendant,Descendant}Serializer`, `CriteriaPlaylistMinimumSerializer` for the shadow playlist, and the kit-provided `build_criteria_detailed_tracks_fields(...)` helper for the tracks/tracks_count/tracks_archived_count fields.

## Settings model

Swappable-model settings — exactly these four, identical in `grow/settings.py` and `tests/settings.py`:

```python
CRITERIA_MODEL = "grow.Criteria"
TRACK_MODEL = "grow.YoutubeTrack"
ARTIST_MODEL = "grow.Artist"
ALBUM_MODEL = "grow.Album"
```

There's no `PLAYLIST_MODEL` or `TAG_MODEL`/`GENRE_MODEL` — Tag/Genre are proxy models of `Criteria` (see above), and Playlist variants resolve through `CRITERIA_MODEL`'s FK graph rather than their own setting.

`tests/settings.py` is independently maintained, not inherited from `grow/settings.py` (see `CLAUDE.md` for the general warning about this). Concrete divergences: in-memory SQLite instead of Postgres, no CORS/Host-validation/CamelCase middleware, hardcoded dummy secrets (`SECRET_KEY`, `GROW_API_KEY`, `GROW_PROTOTYPE_API_KEY`), and a hardcoded `API_ROOT_BASE = "v0/"` instead of one derived from `APP_VERSION`.

## Exception handling

See `CLAUDE.md`'s Architecture section for the full behavior (JSON-forcing under pytest, unlogged fallthrough to a generic 500) — wired identically in both settings modules via `REST_FRAMEWORK["EXCEPTION_HANDLER"] = "the_music_tree_api_kit.view.error.exception_handler.custom_exception_handler"`.

## Testing & CI

Pytest config (`pyproject.toml`): `DJANGO_SETTINGS_MODULE = "tests.settings"`, `--cov-fail-under=85`. CI (`.github/workflows/test.yml`) runs three jobs on PRs into `main`/`develop`: **Lint** (`ruff check`, `ruff format --check`, and `mypy grow` all as steps within this one job — not a separate mypy job), **Migration check** (`makemigrations --check --dry-run`), **Pytest**.
