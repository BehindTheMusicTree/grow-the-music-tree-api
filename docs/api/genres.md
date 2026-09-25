# Genres

## Overview

Manage genre hierarchies and trees.

## Base Path

`/v1/genres/`

Authentication: `X-API-Key` header (single static key, `PIPELINE_API_KEY`). grow-api is a
single-tenant service — this is the canonical reference dataset, not scoped per user.

## Endpoints

#### List

`GET {base}`

#### Retrieve

`GET {base}{id}/`

#### Create

`POST {base}`

#### Update

`PUT {base}{id}/`

#### Delete

`DELETE {base}{id}/`

#### Tree

`GET {base}tree/`

#### Import Tree

`POST {base}tree/import/`

Each node may carry an optional `id` (a Wikidata QID, e.g. `"Q9778"`). Nodes with an `id` are
matched against existing genres by `id` and updated in place; nodes without one are always
created as new genres. Existing genres with no `id` are never touched by import. `id` is not
exposed on any read endpoint (List/Retrieve/Tree) — it's import-only.
