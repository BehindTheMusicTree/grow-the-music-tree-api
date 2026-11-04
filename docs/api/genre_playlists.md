# Genre Playlists

## Overview

Playlists derived from the genre criteria tree.

## Base Path

`/v1/genre-playlists/`

Authentication: `X-API-Key` header (single static key, `PIPELINE_API_KEY`).

## Endpoints

#### List

`GET {base}`

`?treeName=canonical|regional` picks one genre tree. `canonical` also returns the Genreless
playlist. An unknown value returns 400.

Each playlist (here, in Retrieve, and in `{base}tree/`) carries `tracksCount`, its playable songs, and
`viewsCount`, the sum of those same songs' YouTube view counts (a song without one counts as 0). Both
cover the whole primary subtree. The database keeps `viewsCount` current, so it moves with every import,
curation edit and deletion.

#### Tree

`GET {base}tree/?treeName=canonical|regional`

Every genre playlist of the tree, with `tracksCount` and `viewsCount` as above, plus `songsCount` (all
canonical songs in the primary subtree, playable or not: what `library/songs/?genre=<uuid>` lists). In the canonical tree,
the Genreless playlist's `songsCount` is the songs without a genre.

#### Retrieve

`GET {base}{id}/`

#### Tracks

`GET {base}{id}/tracks/`

Paginated, position-ordered page of `{position, track}`. Tracks carry no nested `playlists`.

Read-only: playlists are derived from the criteria tree, not directly editable.
