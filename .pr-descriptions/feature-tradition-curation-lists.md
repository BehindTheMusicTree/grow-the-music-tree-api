## Summary

Four curation lists for the geohistory pipeline's music traditions (≤1950 genealogy): `tradition_additions`, `tradition_exclusions`, `tradition_placement_overrides`, `tradition_link_overrides`. Curation only corrects what the pipeline derives from Wikidata.

## Changes

- `grow/curation/lists.py`: the four lists (source `geohistory`), a `tradition_id` column kind (QID), `COLUMN_CHOICES` for the enumerated `kind` (`lineage|association`) and `action` (`add|remove`) columns; a non-key `entity_id` is optional.
- `grow/curation/rows.py`: validates QID and enumerated columns; an optional column can no longer be a key.
- Migration `0076`, empty seed CSVs, changelog.
- Export CSVs: `manual_tradition_additions.csv` (`wikidata_id,reason`), `manual_tradition_exclusions.csv` (`wikidata_id,reason`), `manual_tradition_placement_overrides.csv` (`wikidata_id,entity_id,start_year,end_year,reason`; blank keeps the derived value), `manual_tradition_link_overrides.csv` (`from_wikidata_id,to_wikidata_id,kind,action,reason`, keyed by from+to+kind).

## Test plan

- [x] `uv run pytest` (curation API tests for QID validation, optional placement fields, enumerated kind/action)
- [x] `ruff check` / `ruff format`
