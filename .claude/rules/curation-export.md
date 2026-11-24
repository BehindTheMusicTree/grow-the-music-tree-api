---
paths:
  - "grow/curation/**/*.py"
  - "grow/view/curation.py"
  - "grow/model/curation/**/*.py"
---

# Curation export format

`GET /v1/curation/export/` feeds `the-music-tree-pipelines`, whose ingest is strict: each list must carry exactly its expected columns (`set(row) != set(columns)` raises `ValueError` in `pipelines/curation/src/curation/ingest.py`). Any added, removed or renamed column breaks the next pipeline run. It fails fast and corrupts nothing.

- Ship format changes as a coordinated release: grow first, then pipelines bump to the new format before the next prod run (prod runs on a daily timer, staging only manually). Roll back by reverting both.
- Do not add a version parameter or a legacy projection for a format change by default.
- When rows migrate progressively, add the column as optional in grow and give pipelines a fallback for rows without it.
- Add a legacy projection only when grow and pipelines cannot be deployed together. Then put a removal condition in a comment next to it and open a follow-up issue that references it. Existing examples: `overview_status_overrides` and `genre_alias_version`.
- A change here also needs a pipelines PR. Pipelines' `AGENTS.md` points back to this rule.
