## Summary

- Release v14.1.0: curator role (`CURATION_API_KEY`, **required env var**), geohistory curation lists (`entity_additions`, 4 tradition lists), genealogy snapshot (`POST genealogy/import/`, public `GET genealogy/` with ETag/304), YouTube view count on songs, artist search performance (migration `0075` rewrites `grow_artist` under lock, apply outside an artist import), `recordingCount` counting every credited song.

## Test plan

- [x] Covered by the feature PRs' CI (Lint, Migration check, Pytest, Perf)
