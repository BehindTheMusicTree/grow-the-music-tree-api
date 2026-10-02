## Summary

First API step of the admin curation editor (grow-frontend): lets the editor show list sizes, search, sort by recency, and display genre names instead of bare QIDs.

- `GET /v1/curation/lists/`: each list now has a `count` (canonical entries).
- `GET /v1/curation/<list>/entries/`:
  - `?q=`: case-insensitive match on key, values (JSON as text), reason, or the name of the canonical genre whose QID is the entry key.
  - `?ordering=key` (default) or `-updated_on`, which sorts by last edit, falling back to creation because `updated_on` is null until the first edit. Any other value returns 400.
  - `labels`: a `{QID: canonical genre name}` map for every item-id column on the page.

## Tests

`tests/integration/curation/test_curation_api.py`: counts, search on each field, recency ordering, invalid ordering, and labels across `item_id`/`parent_item_id`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
