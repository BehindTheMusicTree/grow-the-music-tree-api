# Region-map performance input

`region_map_index.json.gz` pins the public staging index fetched on 2026-11-07
from `https://grow-api-staging.themusictree.org/v1/regions/map/`, with identity
encoding. API revision: `4d8c7f50a4c2d02481063f01c98bb0c553c6136e`.

- Uncompressed SHA-256: `5ee2f9b26dcd1ea79b3d1768ed740a8ba332e41362d4dbab8cdbfec00a8048f2`
- Uncompressed bytes: 636,852
- Drawn regions: 849

The fixture is gzipped with `mtime=0`. The benchmark seed installs its stored
response directly: these benchmarks exercise public reads, not pipeline import
performance. Existing genre/song Gold fixtures remain unchanged; not every
region-referenced genre is guaranteed to occur in those older exports. Lexicon
latency calibration must record the actual number of resolved genre rows.

The seed also runs on reused performance databases. A different existing snapshot
fails explicitly and requires recreating the benchmark database. Refresh this
input only alongside new measurements and reviewed ceilings. Region latency
scenarios and CI calibration are still pending; installing this fixture adds no
new latency guarantee.
