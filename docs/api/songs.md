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

#### Import

See the songs import runs in the [README](../../README.md#api) and `grow/track/bulk_import/`.
