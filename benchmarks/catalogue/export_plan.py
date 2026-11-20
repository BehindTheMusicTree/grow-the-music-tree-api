"""Export plan for the catalogue bundle: which tables a dump carries, and the schema and projections it was planned on.

Grow owns the classification, so the infrastructure that runs `pg_dump` reads this plan instead of keeping a table list
of its own. Pure and stdlib-only: `export_perf_catalogue --plan` supplies the observations. Unlike the rest of the
harness this module ships in the application image (see `.dockerignore`).
"""

import hashlib

from .catalogue_restore import DERIVED, EMPTY, REBUILD, RETAIN, verify_inventory

VERSION = 1
# Projection table -> the singleton state table that stores the fingerprint of the definition that built it.
PROJECTION_STATES = {
    "grow_song_search": "grow_song_search_state",
    "grow_artist_song": "grow_artist_song_state",
}


def build_plan(inventory_tsv: str, fingerprints: dict[str, str]) -> dict:
    """Refuses a schema that drifted from the reviewed inventory and a projection whose fingerprint is not stamped."""
    verify_inventory(inventory_tsv)
    if fingerprints.keys() != PROJECTION_STATES.keys() or not all(fingerprints.values()):
        raise ValueError("a stamped fingerprint is required for every projection")
    return {
        "version": VERSION,
        "inventory_sha256": hashlib.sha256(inventory_tsv.encode()).hexdigest(),
        "data_tables": sorted(RETAIN | DERIVED),
        "schema_only_tables": sorted(EMPTY | REBUILD),
        "projections": {
            table: {"state_table": PROJECTION_STATES[table], "fingerprint": fingerprints[table]}
            for table in sorted(PROJECTION_STATES)
        },
    }
