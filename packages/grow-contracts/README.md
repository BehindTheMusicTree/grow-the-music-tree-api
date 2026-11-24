# the-music-tree-grow-contracts

Contracts of the documents exchanged with
[`grow-the-music-tree-api`](https://github.com/BehindTheMusicTree/grow-the-music-tree-api), which owns them: it
validates the imports and produces the export. Requires Python 3.12 or newer and jsonschema; Django is not required.

```python
from the_music_tree_grow_contracts import SCHEMA_NAMES, first_error, load_schema, validator
from the_music_tree_grow_contracts.curation_lists import CURATION_LISTS, EDGE_COLUMNS
```

| Schema | Document |
| --- | --- |
| `artist` | Artist import row |
| `genealogy` | Music tradition genealogy import |
| `region_map`, `hidden_regions`, `synthesized_overview_alerts` | Files of a region map import |
| `curation_resolutions` | Curation resolutions the pipeline reports |
| `curation_export` | `GET /v1/curation/export/?genre_alias_version=2` response |

`curation_export.schema.json` is generated from `curation_lists.py`. After changing a list, regenerate it from the
repository root:

```bash
uv run python -m the_music_tree_grow_contracts.generate
```
