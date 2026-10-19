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
`tracksCount` counts the recordings with a genre, the ones the library lists.

An artist's recordings: `GET /v1/library/recordings/?artist=<uuid>&ordering=title|-title|albumYear|-albumYear`
(nulls last). `albumYear` uses the recording's `first_release_year` where the pipelines supply one, falling back to a
four-digit album year; recordings with neither sort with the nulls.

`GET /v1/library/recordings/?playable=true|false`: playable means `youtube_video_id` is set and
`youtube_unplayable_reason` is empty.
`?from=<recording uuid>` starts the list at that recording (included) in the current ordering (default `created_on`;
nulls last, ties by id). 404 if it is not in the filtered list, 400 if not a UUID.

`isSpecialPurpose` (read-only boolean, also on nested artists) is true for the special-purpose MBIDs (Various Artists,
Unknown, etc.).

#### Import

Staged like the songs import, run by the nightly pipeline **after** the songs import (so song artists already carry
their MBID):

1. `POST {base}import-runs/` → `{runId}`
2. `PUT {base}import-runs/<runId>/parts/<n>/` per gzip NDJSON part, one artist per line:
   `{musicbrainz_artist_id, name, type, country, begin_year, end_year, ended, members: [{musicbrainz_artist_id, begin_year, end_year, ended, roles}], links: [{kind, url}], release_groups: [{musicbrainz_release_group_id, title, primary_type, secondary_types, first_release_year}]}`
3. `POST {base}import-runs/<runId>/commit/` → `{taskId}`
4. `GET {base}import/<taskId>/status/`

Creating a run abandons any uncommitted artists run. The merge upserts artists on MBID, replaces their memberships
(members missing from the database are skipped), links and release-group album credits, and deletes artists missing
from the run that no track or hand-made album credits. An empty run is rejected.

**Delta runs.** `POST {base}import-runs/` with `{"mode": "delta"}` (default `full`) makes the run carry only changed
artists. Deleted artists are listed in a gzip NDJSON body of `{musicbrainz_artist_id}` lines sent with
`PUT {base}import-runs/<runId>/deletions/` before the commit. The merge upserts the run's artists and deletes only the
listed ones (same credit guards); nothing else is deleted, and a run with no artists is accepted.
