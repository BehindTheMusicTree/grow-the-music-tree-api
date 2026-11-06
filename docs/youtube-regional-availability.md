# YouTube regional availability

`Song.youtube_region_restriction` and the import staging field describe the selected video only. Null means metadata is unknown; otherwise the policy is `{mode: allowed|blocked|unrestricted, countries: [...]}`. Countries are unique, sorted uppercase two-letter codes. An empty allowed list blocks everywhere; an empty blocked list permits an attempt everywhere. Global `youtube_unplayable_reason` remains independent.

Migration `0104` adds nullable JSON fields without a backfill. Legacy exports remain accepted with unknown policy. A regional-only import change updates the song and invalidates search without changing shared playlist memberships or aggregate counts. Manually edited songs retain their video and global reason; incoming policy and view count apply only when the staged video matches the selected video.

`GET playback/context/` returns `{country: string|null}`. Country is accepted only with the configured `VIEWER_CONTEXT_TOKEN` in `X-Viewer-Context-Token`, alongside `X-Viewer-Country`. Unauthenticated country headers are ignored. An unset server token disables trusted country context. Never expose the token to browser code.

Song serializers add `youtubeVideo.availability` with status `eligible`, `blocked`, or `unknown`, the existing global reason or `region_blocked` or null, and the request country. Unknown policy or country permits an attempt unless a global block or an empty allowed list is known. `playable=true` includes eligible and unknown songs; `playable=false` includes known blocks and missing videos. Playlist eligibility is applied before pagination and anchor lookup; search applies it before branch limits. Search cache keys include the trusted country. Song, playlist-track and playback-context responses are private and no-store.

The frontend authenticates the edge country separately, then forwards the internal API credential. Direct API requests remain unknown. Country is an approximate hint; YouTube playback can still fail. Legacy `region_whitelisted` global reasons need deliberate review against current metadata; imports do not silently reinterpret those manual restrictions.

Validate unit and SQLite integration behavior with `uv run pytest`. COPY/merge and JSONB behavior additionally require the documented `POSTGRES_TEST_DATABASE_URL` test database and `-m postgres --ds=tests.postgres_settings --no-cov`. When testing this branch before a genre-kit release, put its matching worktree `src` on `PYTHONPATH`. Publish and dependency updates are separate release work.
