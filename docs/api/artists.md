# Artists

## Overview

Reference artists with their MusicBrainz details, group memberships, links and release-group albums.

## Base Path

`/v1/artists/`

Reads are public. The import endpoints take the `X-API-Key` header (`PIPELINE_API_KEY`) or an admin token.

## Endpoints

#### List

`GET {base}`

`{uuid, name, albums, tracksCount, createdOn}` per artist, `albums` being `{uuid, name, albumArtists}`.

#### Retrieve

`GET {base}{uuid}/`

```json
{
  "uuid": "…",
  "name": "Radiohead",
  "musicbrainzArtistId": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
  "type": "group",
  "country": "GB",
  "beginYear": 1985,
  "endYear": null,
  "ended": false,
  "links": [{"kind": "official", "url": "https://radiohead.com"}],
  "members": [{"artist": {"uuid": "…", "name": "Thom Yorke"}, "beginYear": 1985, "endYear": null, "ended": false, "roles": ["vocals"]}],
  "memberOf": [],
  "albums": [{"uuid": "…", "name": "OK Computer", "year": "1997", "primaryType": "Album", "secondaryTypes": []}],
  "tracksCount": 42,
  "createdOn": "…",
  "updatedOn": "…"
}
```

`type`: `person|group|orchestra|choir|character|other|null`. `links[].kind`:
`official|wikipedia|wikidata|spotify|youtube|bandcamp|soundcloud|discogs|social`. `memberOf` has the `members` shape,
`artist` being the group. Links are ordered by kind then URL, memberships by `beginYear`, albums by `year` (a four-digit string) then name.
`tracksCount` counts the songs with a genre, the ones the library lists.

#### Genre counts

`GET {base}{uuid}/genre-counts/`

Public. Sparse per-genre-playlist counts of the artist's canonical songs, for pruning the genre tree to the artist's footprint:

```json
[{"genrePlaylist": "…", "songsCount": 12, "tracksCount": 9}]
```

Only non-zero nodes are listed: every genre playlist whose primary subtree holds at least one of the artist's songs, ancestors
included. `songsCount` is all of the artist's songs in the subtree (what `library/songs/?genre=<uuid>&artist=<uuid>`
lists); `tracksCount` only the playable ones, like `tracksCount` in `genre-playlists/tree/`. The artist's genre-less songs
count toward the Genreless playlist. An artist without songs gives `[]`; 404 for an unknown artist.

An artist's songs: `GET /v1/library/songs/?artist=<uuid>&ordering=title|-title|albumYear|-albumYear`
(nulls last). `albumYear` uses the song's `first_release_year` where the pipelines supply one, falling back to a
four-digit album year; songs with neither sort with the nulls.

`GET /v1/library/songs/?playable=true|false`: playable means `youtube_video_id` is set and
`youtube_unplayable_reason` is empty.
`?from=<song uuid>` starts the list at that song (included) in the current ordering (default `created_on`;
nulls last, ties by id). 404 if it is not in the filtered list, 400 if not a UUID.

`isSpecialPurpose` (read-only boolean, also on nested artists) is true for the special-purpose MBIDs (Various Artists,
Unknown, etc.).

#### Search

`GET {base}search/?q=<text>&limit=<n>`

Public typeahead over artist names and MusicBrainz aliases, accent- and case-insensitive and typo-tolerant. `q` is 2-100
characters and `limit` defaults to 10 (max 25); otherwise 400. Special-purpose artists are excluded. Not paginated.

`{uuid, name, disambiguation, type, country, beginYear, endYear, matchedAlias, recordingCount}` per artist, best match
first: exact name, then prefix, then similarity, then `recordingCount`. `matchedAlias` is set only when an alias matched
better than the name. Throttled to 120 requests per minute per client.

#### Import

Staged like the songs import, run by the nightly pipeline **after** the songs import (so song artists already carry
their MBID):

1. `POST {base}import-runs/` → `{runId}`
2. `PUT {base}import-runs/<runId>/parts/<n>/` per gzip NDJSON part, one artist per line:
   `{musicbrainz_artist_id, name, type, country, begin_year, end_year, ended, members: [{musicbrainz_artist_id, begin_year, end_year, ended, roles}], links: [{kind, url}], release_groups: [{musicbrainz_release_group_id, title, primary_type, secondary_types, first_release_year}]}`
3. `POST {base}import-runs/<runId>/commit/` → `{taskId}`
4. `GET {base}import/<taskId>/status/`: polling also re-enqueues a merge lost to a worker restart (it stays `pending` until the re-run finishes)

Creating a run abandons any uncommitted artists run. The merge upserts artists on MBID, replaces their memberships
(members missing from the database are skipped), links and release-group album credits, and deletes artists missing
from the run that no track or hand-made album credits. An empty run is rejected.

**Delta runs.** `POST {base}import-runs/` with `{"mode": "delta"}` (default `full`) makes the run carry only changed
artists. Deleted artists are listed in a gzip NDJSON body of `{musicbrainz_artist_id}` lines sent with
`PUT {base}import-runs/<runId>/deletions/` before the commit. The merge upserts the run's artists and deletes only the
listed ones (same credit guards); nothing else is deleted, and a run with no artists is accepted.
