# Changelog

## 0.2.0

- Breaking: `curation_export` no longer carries `genre_alias_version` (the export is always the id-based genre alias contract) nor the deprecated `overview_status_overrides`; `target_item_id` is a required, non-empty `genre_alias` column; `LEGACY_GENRE_ALIAS_COLUMNS` is removed and `is_optional_column` takes the column only.

## 0.1.1

- Release only: 0.1.0 was tagged by no run (the release policy was new on `main`), so this is the first version published to PyPI. No contract change.

## 0.1.0

- First published version: the Gold contract schemas owned by grow (`artist`, `genealogy`, `region_map`, `hidden_regions`, `synthesized_overview_alerts`, `curation_resolutions`, `curation_export`), `load_schema(name)` and the curation list columns.

## 0.0.0

- Unpublished baseline of the release policy; the first published version is a later bump.
