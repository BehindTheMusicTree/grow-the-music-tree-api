# Tag Playlists

## Overview

Playlists derived from the tag criteria tree.

## Base Path

`/v0/reference/tag-playlists/`

Authentication: `X-API-Key` header (single static key, `GROW_API_KEY`).

## Endpoints

#### List

`GET {base}`

#### Retrieve

`GET {base}{id}/`

Read-only: playlists are derived from the criteria tree, not directly editable.

## Request / Response

### GET /

**Description**
List tag playlists

**Request**
Headers:
X-API-Key: {api_key}

Query params:
page, page_size, name, parent

Body:
None

**Response**
Status codes:
| 200 OK

Body:

```json
{
  "count": 10,
  "next": null,
  "previous": null,
  "results": [
    {
      "uuid": "uuid",
      "name": "string",
      "uploaded_track_playlist_relations": [],
      "uploaded_tracks_count": 10,
      "uploaded_tracks_archived_count": 0,
      "criteria": {},
      "parent": {},
      "root": {},
      "created_on": "2023-01-01T00:00:00Z",
      "updated_on": "2023-01-01T00:00:00Z"
    }
  ]
}
```

### Validation Rules

None

### Business Rules

None

### Errors

Code Meaning
| 400 Bad Request - Invalid parameters
| 401 Unauthorized - Invalid or missing API key
| 404 Not Found - Playlist not found

### GET /{id}/

**Description**
Get tag playlist details

**Request**
Headers:
X-API-Key: {api_key}

Query params:
None

Body:
None

**Response**
Status codes:
| 200 OK

Body:

```json
{
  "uuid": "uuid",
  "name": "string",
  "uploaded_track_playlist_relations": [],
  "uploaded_tracks_count": 10,
  "uploaded_tracks_archived_count": 0,
  "criteria": {},
  "parent": {},
  "root": {},
  "created_on": "2023-01-01T00:00:00Z",
  "updated_on": "2023-01-01T00:00:00Z"
}
```

### Validation Rules

None

### Business Rules

None

### Errors

Code Meaning
| 400 Bad Request - Invalid parameters
| 401 Unauthorized - Invalid or missing API key
| 404 Not Found - Playlist not found

### Notes

None
