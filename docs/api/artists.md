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
(nulls last). Pipeline recordings have no album, so `albumYear` only orders recordings given one by hand.

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
