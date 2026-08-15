# Tags

## Overview

Manage tag hierarchies and trees.

## Base Path

`/v0/reference/tags/`

Authentication: `X-API-Key` header (single static key, `GROW_API_KEY`). grow-api is a
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
