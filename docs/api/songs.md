# Songs

## Overview

Every canonical MusicBrainz song, with or without a genre or a playable video.

## Base Path

`/v1/library/songs/`

Reads are public. Writes take an admin token; the import endpoints take the `X-API-Key` header (`PIPELINE_API_KEY`)
or an admin token.

## Endpoints

#### Retrieve

`GET {base}{uuid}/`

The list fields plus `firstReleaseYear` (null when unknown) and `essentialGenres` (`[{uuid, name}]`). A `PATCH`
answers with the same shape.

#### Search

`GET {base}search/?q=<text>&limit=<n>&genre=any|with|without&playable=true|false`

Public typeahead over song titles and credited artist names. Authentication is ignored, so a stale token can't fail it.
Accents, case and punctuation are folded (`ac/dc` = `ac dc`, `Björk` = `bjork`), and every query word must match a
title or artist word as a prefix, in any order (`queen bohem`). Only the first 8 words count. A query with no letter or
digit returns `[]`.

- `q`: 2-100 characters.
- `limit`: 1-50, default 8.
- `genre`: `with` keeps songs with a genre, `without` keeps genreless ones (the songs an admin still has to link),
  `any` (default) keeps both.
- `playable`: `true` keeps songs with a playable video, `false` keeps the others. Omitted, it keeps both.

Anything else returns 400. Not paginated.

```json
[
  {
    "uuid": "…",
    "title": "Comfortably Numb",
    "artists": [{"uuid": "…", "name": "Pink Floyd", "isSpecialPurpose": false}],
    "genre": {"uuid": "…", "name": "Progressive rock"},
    "youtubeVideo": {"id": "…", "unplayableReason": null, "viewCount": 123456},
    "firstReleaseYear": 1979
  }
]
```

`genre` is null for a genreless song. Results come best match first:

1. A title equal to the query.
2. A title starting with the query.
3. Any other match.

Within each tier, songs are ordered by a static rank. Having a genre weighs most, then a playable video, then
popularity: MusicBrainz recording count and YouTube views, each on a capped log scale (`grow/song_search/rank.py`).

Responses are cached per query until the next song, artist or genre write. Throttled to 120 requests per minute per
client.

Error responses:

- 503 with `details.code: "search_unavailable"` until the projection has been built once
  (built automatically after the first import that finds it unbuilt; `manage.py rebuild_song_search` forces it).
- 503 with `details.code: "query_timeout"` when the query exceeds its 3 s statement timeout.

Search reads `grow_song_search`, a projection of the songs (title and artist words, genre and playable flags, rank).
Once built, the songs and artists merges keep it current in the same transaction, and so do the song and genre ORM writes.
While it is unbuilt, the merges skip it and queue one bulk build (`song-search-build` task) after they commit.
`manage.py rebuild_song_search` rebuilds it from scratch and swaps it in. Searches keep being served while it runs,
but song, artist and genre writes wait for it, imports included: run it outside the nightly pipeline window. `manage.py rebuild_song_search --check` prints the `missing`, `orphaned` and `stale` row counts and
fails if any of them is non-zero.

#### List by genre

`GET {base}?genre=<uuid>&coverage=genre_and_subgenres&subgenres=<scope>`

With inclusive coverage, contract 4 supports `restricted` (direct songs plus restricted descendants),
`extended` (direct songs plus all accessible descendants), and `expressions` (the additional descendants reached
by extended coverage). The exact `coverage=genre_only` selects only directly assigned songs and rejects `subgenres`.

For existing clients, `canonical` aliases `restricted`, `all` aliases `extended`, and `regional` selects
`expressions` plus direct songs. The default is `canonical` for canonical genres and `all` for regional genres.
Regional genres only accept `all` among the legacy values. Contract 4 scopes work for either tree.

#### List by artist

`GET {base}?artist=<uuid>&ordering=title|-albumYear&cursor=<opaque>&page_size=<n>`

Only `artist`, `ordering` (default `title`), `cursor`, `page_size` and `with_total` are accepted; any other parameter
returns 400, as do an unknown ordering or an invalid cursor. Pages are keyset pages: `next` carries the `cursor` of the
following page and is null on the last one. `count`, `page` and `totalPages` are null, `previous` is always null.
Songs without an album year come last under `-albumYear`.

The page is read from `grow_artist_song` (one row per artist and credited song, with the title and album year sort
keys), so the cost stays flat for an artist with 100 k+ songs. The songs and artists merges keep it current in their
transaction, and so do the song, album and credit ORM writes. While it is unbuilt the merges skip it, and the endpoint
returns 503 (no fallback to the unindexed query). `manage.py rebuild_artist_song` builds it; `--check` prints the drift
from the songs and fails if there is any.

#### Import

See the songs import runs in the [README](../../README.md#api) and `grow/track/bulk_import/`.

Song imports require a published reference graph, reviewed revisions and a complete assignment stream. A request using the legacy song import protocol returns 400. An accepted commit queues publication and returns 202.

Create a semantic run at `POST songs/import-runs/` with `mode`, `graphRevision`, `membershipRevision` and `expectedParts`. Both revisions must be the explicitly reviewed UUIDs from the reference graph API; a stale review returns 409 before abandoning existing uploads. `expectedParts` declares the number of zero-based parts in each stream, for example `{"songs": 2, "assignments": 2}`. A delta also declares `deletions` as 0 or 1; an empty delta explicitly declares all three counts as 0. Full runs require at least one song part.

Upload song parts as before. Upload assignment parts to `PUT songs/import-runs/<runId>/assignments/parts/<n>/`, as gzip NDJSON. Each line contains `musicbrainz_recording_id` and `assignments`, a complete identity-to-evidence map with zero or one identity:

```json
{"musicbrainz_recording_id":"b1a9c0e9-d987-4042-ae91-78d6a3267d69","assignments":{"LOCAL:dub":[{"decisionId":"review-123","source":"curation","rationale":"Reviewed attribution"}]}}
```

A song has at most one directly assigned genre; several independent evidence decisions may support that genre. Semantic parent genres are inherited through the graph, with duplicate paths counted once. Rows assigning two identities are rejected, including for locked songs. An explicitly unassigned song has `"assignments": {}`. Every imported song, including a manually locked song, needs exactly one complete assignment row. Unknown/retired identities, conflicting or changed evidence, duplicate assignment rows and duplicate JSON object keys are rejected. Locked songs retain their current assignments and history after validation of the uploaded set.

Uploading a part replaces that part and its durable receipt in one transaction. Upload, commit and abandonment serialize on the run, and a body still being spooled is rechecked before COPY. Commit checks every declared receipt against staging row counts, so a PostgreSQL restart that truncates the unlogged staging tables requires reupload rather than silently treating missing data as an empty delta. Abandonment and finalization remove all staging streams and receipts together. The queued merge repeats completeness validation before business writes.
