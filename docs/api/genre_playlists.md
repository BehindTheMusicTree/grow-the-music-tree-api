# Genre Playlists

## Overview

Playlists derived from the genre criteria tree.

## Base Path

`/v0/reference/genre-playlists/`

Authentication: `X-API-Key` header (single static key, `GROW_API_KEY`).

## Endpoints

#### List

`GET {base}`

#### Retrieve

`GET {base}{id}/`

Read-only: playlists are derived from the criteria tree, not directly editable.
