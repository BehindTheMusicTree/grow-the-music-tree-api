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

`GET {base}tree/?treeName=canonical|regional`

`treeName` is required; a missing or unknown value returns 400.

#### History

`GET {base}{id}/history/`

Public. The genre's modification log, newest first:

```json
[
  {
    "uuid": "…",
    "action": "parent_changed",
    "actorPseudo": "Gardener",
    "oldValue": null,
    "newValue": "Electronic",
    "createdOn": "2026-09-30T12:00:00Z"
  }
]
```

`action` is one of `created`, `parent_changed`, `renamed`, `excluded`, `deleted`,
`name_conflict_resolved`, `root_accepted`. `actorPseudo` is the admin's public pseudo, or `null`
when the pipeline import made the change. No email is ever exposed. Pseudos are set server-side
with `manage.py set_user_pseudo <email> <pseudo>`.

#### Import Tree

`POST {base}tree/import/`

Body: `{"treeName": "canonical"|"regional", "tree": [...]}`. `treeName` is required. Only
`regional` nodes may carry several `primaryParents`.

Each node may carry an optional `id` (a Wikidata QID, e.g. `"Q9778"`). Nodes with an `id` are
matched against existing genres by `id` and updated in place; nodes without one are always
created as new genres. Existing genres with no `id` are never touched by import. `id` is not
exposed on any read endpoint (List/Retrieve/Tree) — it's import-only.
