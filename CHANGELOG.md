# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## Guidelines for Contributors

- Add entries to the `[Unreleased]` section under the appropriate category: `Added`, `Changed`, `Improved`, `Deprecated`, `Removed`, `Fixed`.
- Group related changes together; write clear, user-focused descriptions rather than raw git log dumps.
- Mention tests within the related feature or fix entry — "Test" is not its own category.
- This project has no tagged releases yet, so there is no versioned-section history below `[Unreleased]`. Once releases start, move `[Unreleased]` entries into a dated `## [X.Y.Z] - YYYY-MM-DD` section.

## [Unreleased]

### Fixed

- Fixed `CriteriaPlaylist.DoesNotExist` on deleting a root `Genre` or `Tag`: the catch-all criteria-less `CriteriaPlaylist` row per `(user, type)` that `TrackManager`/`CriteriaPlaylistManager` assume exists was never created. A `post_save` signal now bootstraps it for new users, and a data migration backfills it for existing users.
- Fixed tracks directly attached to a deleted root `Tag` being silently orphaned instead of moved to the criteria-less playlist: `CriteriaManager._on_before_delete` looked up "direct tracks to transfer" via the `Genre`-specific FK-leaf relation, which is always empty for `Tag`. Added regression tests covering root `Genre` deletion, root `Tag` deletion, and a track transitioning to genreless.

### Changed

- Re-pinned `the-music-tree-api-kit` to `v0.2.0` and `the-music-tree-genre-kit` to `v0.3.0`; `TrackPlaylistRel`, `TrackPlaylistRelManager`, `CriteriaPlaylist`, and `CriteriaPlaylistManager` are now thin subclasses of the shared kit abstractions, removing near-duplicate logic previously maintained separately from `hear-the-music-tree-api`. No schema or behavioral changes.
- Re-pinned `the-music-tree-genre-kit` to `v0.4.0` and removed `CriteriaManager._get_direct_tracks`/`_on_before_delete`: this orchestration is now hoisted into the kit's `AbstractCriteriaManager`, which fixes the same root-`Tag`-deletion bug generically for any consuming app. `GenreManager._get_direct_tracks` is unchanged. No schema or behavioral changes.
- Re-pinned `the-music-tree-genre-kit` to `v0.5.1`; grow's local `Track` model is retired in favor of the kit's shared `Track` (Django MTI) — `UploadedTrack`/`YoutubeTrack` now inherit it directly. `TrackManager` is a thin subclass of the kit's `AbstractTrackManager`, removing near-duplicate genre-playlist and album/artist orphan-cleanup logic. Data migration copies existing `grow_track` rows into the kit's table under the same PK before dropping grow's local table; both steps are separate migrations so a bad deploy can be halted after the additive step without a destructive rollback. Playlist-membership access (`instance.playlists`, used by the youtube/uploaded track serializers) is reconstructed via a new `TrackConvenienceMixin.playlists` property, since the kit's `Track` intentionally has no `playlists` M2M field. No API-visible behavior change.
- `settings.TRACK_MODEL` now points at `grow.YoutubeTrack` directly instead of the kit's base `Track`. grow has exactly one concrete track type, so `TrackConvenienceMixin.resolve_concrete()` and its disambiguation logic are removed entirely, along with the dead `UploadedTrack` model/table (no live API surface). Serializers and `Play.content`/`content_type` resolution now reference `YoutubeTrack` directly instead of downcasting from the shared base `Track`.
