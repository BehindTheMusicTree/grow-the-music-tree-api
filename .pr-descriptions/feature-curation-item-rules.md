## Summary

Second API step of the admin curation editor. It adds a "rules for this genre" view and the genre autocomplete.

- `GET /v1/curation/rules/?item_id=<QID|LOCAL:slug>` returns every canonical entry referencing the item, across all lists. An entry matches when the item is:
  - its key;
  - part of a composite key (`regional_secondary_parents` keys hold `parent_id`);
  - any item-id value (`parent_item_id`, `overview_item_id`, …).

  The response is `{results: [{listName, uuid, row, createdOn, updatedOn}], labels}`, ordered by list then key. An invalid id returns 400.
- New `find_item_rules(queryset, item_id)`. `find_parent_rule` is now a filter on it; the exclusion guard and migration 0036 behave the same.
- `GenreSimpleSerializer` now exposes `wikidataId`. The duplicate `GenreNameConflictMemberSerializer` is removed. `GenreFilterSet` gets an exact `?wikidata_id=` filter.

## Tests

- `test_curation_api.py`: rules found by key, by value, and by the second part of a composite key, with no false prefix match (`Q…10`); invalid id returns 400.
- `test_edit_curation_rules.py`: list genres by `wikidata_id`.
- Existing exclusion-guard tests pass unchanged. Full suite: 277 passed; mypy is clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
