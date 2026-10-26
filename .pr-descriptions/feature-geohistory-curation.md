## Summary
Adds three curation lists the `geohistory` pipeline needs to correct its cultural-entity graph: `entity_exclusions`, `entity_membership_overrides` and `entity_time_span_overrides`. They are served by the existing curation endpoints and the `curation/export/` the pipeline ingests.

## Changes
- `grow/curation/lists.py`: `geohistory` source, the three lists, and `entity_id` / `int` column kinds in `column_specs`.
- `grow/curation/rows.py`: row validation. Entity ids must be a Glottocode (`abcd1234`) or a Wikidata QID (`Q123`); years must be integers (empty allowed).
- Migration `0071_geohistory_curation_lists` (`list_name` choices) and empty header-only seed CSVs.
- `CHANGELOG.md` entry.

## Test plan
- [x] `pytest tests/integration/curation`: 115 passed (new cases: valid ids, invalid id, integer/empty years)
- [x] `ruff check` / `ruff format --check`
- [x] `makemigrations --check`: no drift

Must merge before the `the-music-tree-pipelines` change that adds these lists to `curation.ingest`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
