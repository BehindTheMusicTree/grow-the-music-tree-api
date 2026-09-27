# Genre Playlists

## Overview

Playlists derived from the genre criteria tree.

## Base Path

`/v1/genre-playlists/`

Authentication: `X-API-Key` header (single static key, `PIPELINE_API_KEY`).

## Endpoints

#### List

`GET {base}`

#### Retrieve

`GET {base}{id}/`

#### Tracks

`GET {base}{id}/tracks/`

Paginated, position-ordered page of `{position, track}`. Tracks carry no nested `playlists`.

Read-only: playlists are derived from the criteria tree, not directly editable.
