# Genres

## Overview

Manage genre hierarchies and trees.

## Base Path

`/v1/genres/`

Authentication: `X-API-Key` header (single static key, `PIPELINE_API_KEY`). grow-api is a
single-tenant service — this is the canonical reference dataset, not scoped per user.

## Reference graph

`PUT {base}graph/` (pipeline or admin) takes `graph`, `mapping` and `expectedRevision`. A `null` mapping
keeps the identity's existing binding; otherwise it adopts the ownerless genre whose `wikidata_id` equals the
identity (never by label), or creates a genre. Several genres sharing that `wikidata_id`, or one already bound
to another identity, answer 400 and change nothing.

A genre created in the admin without a `wikidata_id` is adopted as a local node: it gets `wikidata_id`
`LOCAL:<slug>`, a `canonical_parent_additions` row and a parent edge, so the pipelines recreate the node under the
same id and this import binds it. Creating a regional or excluded genre, or a root without a parent, answers 400
(`treeName` and `parent` fields respectively), since neither can be expressed as a `LOCAL:` node. Migration `0154`
adopts the existing app-created genres the same way; a genre whose chain has no adoptable parent is skipped and logged.

## Endpoints

#### List

`GET {base}`

#### Retrieve

`GET {base}{id}/`

#### Create

`POST {base}`

#### Update

`PUT {base}{id}/`

#### Make root

`PUT {base}{id}/` with `parent: null` (admin only)

Detaches a canonical genre from its parent so it becomes a root. For a Wikidata-backed genre it also replaces the item's `canonical_parent` edge with a parentless one (a root), so the next pipeline import keeps it a root. The genre is locked, `isUnacceptedRoot` is cleared and a `parent_changed` history entry (`newValue` null) is recorded. Returns 400 for regional or excluded genres; a genre that is already a root is a no-op. Giving the root a parent again (`PUT` with a non-null `parent`) replaces that parentless edge, since an item holds a single `canonical_parent` edge.

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

`action` is one of `created`, `parent_changed`, `renamed`, `side_changed`, `excluded`,
`genre_changed`, `updated`, `deleted`, `name_conflict_resolved`, `root_accepted` (the shared
`HistoryAction` enum: genres never record `genre_changed` or `updated`, but clients should accept
every value). `side_changed` carries `core`/`pop` in `oldValue`/`newValue`. `actorPseudo` is the admin's public pseudo, or `null`
when the pipeline import made the change. No email is ever exposed. Pseudos are set server-side
with `manage.py set_user_pseudo <email> <pseudo>`.

#### Import Tree

`POST {base}tree/import/`

Body: `{"treeName": "canonical"|"regional", "tree": [...]}`. `treeName` is required. Only
`regional` nodes may carry several `primaryParents`.

An `X-API-Key` import also requires `curationExportedOn` (ISO 8601): the curation export's
`exported_on` the tree was built from. It becomes the applied export, so curation edits made after
it stay pending. 400 if missing, unparseable, or later than the last curation export. Admin imports
must not send it.

Each node may carry an optional `id` (a Wikidata QID, e.g. `"Q9778"`). Nodes with an `id` are
matched against existing genres by `id` and updated in place; nodes without one are always
created as new genres. Existing genres with no `id` are never touched by import. `id` is not
exposed on any read endpoint (List/Retrieve/Tree) — it's import-only.
