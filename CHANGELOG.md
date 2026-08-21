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
