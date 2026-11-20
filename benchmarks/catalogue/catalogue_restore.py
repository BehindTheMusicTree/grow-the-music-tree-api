"""Trusted in-place catalogue projection, before candidate database access.

Run only in a fresh, inaccessible scratch database before post-data constraints
and triggers. This generates SQL, not candidate access or a successful restore
receipt. Schema SQL approval, derived-data rebuilding, migration compatibility,
sequence repair and post-data verification remain executor responsibilities.
"""

import hashlib
from dataclasses import replace
from pathlib import Path

from .manifest import matching
from .sanitization import IDENTIFIER, Policy

TRACK = "the_music_tree_genre_kit_track"
PLAYLIST = "the_music_tree_genre_kit_playlist"
GRAPH = "the_music_tree_genre_kit_genregraph"
TYPES = "the_music_tree_genre_kit_criteriatype"
SCHEMA = Path(__file__).with_name("catalogue-schema.tsv")

# Every new table requires a reviewed decision, including tables whose data is
# excluded. Opaque snapshots can embed private objects, so are never copied.
EMPTY = frozenset(
    [
        "auth_group",
        "auth_group_permissions",
        "auth_permission",
        "auth_user",
        "auth_user_groups",
        "auth_user_user_permissions",
        "django_content_type",
        "django_migrations",
        "django_q_ormq",
        "django_q_schedule",
        "django_q_task",
        "grow_artist_import_staging",
        "grow_bulk_import_deletion",
        "grow_bulk_import_run",
        "grow_curation_entry",
        "grow_curation_review_item",
        "grow_curation_sync_state",
        "grow_genealogy_snapshot",
        "grow_genre_edge_rule",
        "grow_genre_tree_import_payload",
        "grow_genregraphassignmentbackup",
        "grow_genregraphimport",
        "grow_history_entry",
        "grow_import_attempt",
        "grow_import_part",
        "grow_import_receipt",
        "grow_import_run",
        "grow_manual_playlist",
        "grow_pipeline_run_request",
        "grow_play",
        "grow_region_map_file",
        "grow_region_map_file_staging",
        "grow_region_map_snapshot",
        "grow_song_assignment_staging",
        "grow_song_genre_undo",
        "grow_song_import_staging",
        "grow_user_profile",
        "the_music_tree_genre_kit_importrun",
    ]
)
REBUILD = frozenset(
    [
        "grow_genre_catalogue_count",
        "grow_genre_membership_count",
        "grow_genre_tree_version",
    ]
)
# Projections whose data is retained: expensive to rebuild (song search takes hours at catalogue scale), pruned to the
# retained songs and artists, and revalidated by preparation (`rebuild_* --if-stale`, which compares the fingerprint
# of the definition that built them).
DERIVED = frozenset(
    [
        "grow_artist_song",
        "grow_artist_song_state",
        "grow_song_search",
        "grow_song_search_state",
    ]
)


def missing_reference(column: str, table: str, key: str = "uuid") -> str:
    for identifier in (column, table, key):
        matching(identifier, IDENTIFIER, "catalogue identifier")
    return f'NOT EXISTS (SELECT 1 FROM "public"."{table}" AS retained WHERE retained."{key}" = candidate."{column}")'


# Keep each rejection as a top-level DELETE predicate so PostgreSQL can use
# spillable anti joins even before post-data indexes exist. A negated IN below
# IS NOT TRUE can fall back to rescanning a materialized 32-million-row subplan.
ROOTS = {
    "grow_album": ('"user_id" IS NOT NULL',),
    "grow_artist": ('"user_id" IS NOT NULL',),
    "grow_criteria": ('"user_id" IS NOT NULL',),
    TRACK: ('"user_id" IS NOT NULL', missing_reference("uuid", "grow_song", "track_id")),
    PLAYLIST: ('"user_id" IS NOT NULL', missing_reference("uuid", "grow_criteria_playlist", "playlist_id")),
}


DEPENDENTS = {
    "grow_song": (missing_reference("track_id", TRACK),),
    "grow_genre": (missing_reference("criteria_ptr_id", "grow_criteria"),),
    "grow_criteria_playlist": (
        missing_reference("playlist_id", PLAYLIST),
        '"criteria_id" IS NOT NULL AND ' + missing_reference("criteria_id", "grow_criteria"),
    ),
    "grow_album_album_artists": (
        missing_reference("album_id", "grow_album"),
        missing_reference("artist_id", "grow_artist"),
    ),
    "grow_artist_alias": (missing_reference("artist_id", "grow_artist"),),
    "grow_artist_link": (missing_reference("artist_id", "grow_artist"),),
    "grow_artist_membership": (
        missing_reference("group_id", "grow_artist"),
        missing_reference("member_id", "grow_artist"),
    ),
    "grow_criteria_lineage_rel": (
        '"user_id" IS NOT NULL',
        missing_reference("ascendant_id", "grow_criteria"),
        missing_reference("descendant_id", "grow_criteria"),
    ),
    "grow_criteria_additional_primary_parents": (
        missing_reference("from_criteria_id", "grow_criteria"),
        missing_reference("to_criteria_id", "grow_criteria"),
    ),
    "grow_criteria_secondary_parents": (
        missing_reference("from_criteria_id", "grow_criteria"),
        missing_reference("to_criteria_id", "grow_criteria"),
    ),
    "grow_genre_essential_songs": (
        missing_reference("genre_id", "grow_genre", "criteria_ptr_id"),
        missing_reference("song_id", "grow_song", "track_id"),
    ),
    f"{GRAPH}attribution": (missing_reference("track_id", TRACK),),
    f"{GRAPH}attributionevidence": (missing_reference("attribution_id", f"{GRAPH}attribution", "id"),),
    f"{GRAPH}assignmentstate": (missing_reference("track_id", TRACK),),
    f"{GRAPH}attributionrevision": (missing_reference("track_id", TRACK),),
    f"{TRACK}_artists": (missing_reference("track_id", TRACK), missing_reference("artist_id", "grow_artist")),
    f"{TRACK}_playlist_rel": (
        '"user_id" IS NOT NULL',
        missing_reference("track_id", TRACK),
        missing_reference("playlist_id", PLAYLIST),
    ),
    # Derived rows carry titles and names: pruning them with their sources is a privacy requirement too. The state
    # tables are singletons without references.
    "grow_song_search": (missing_reference("track_id", "grow_song", "track_id"),),
    "grow_artist_song": (
        missing_reference("song_id", "grow_song", "track_id"),
        missing_reference("artist_id", "grow_artist"),
    ),
}


# Canonical graph tables hold no user_id: only the track-keyed ones are pruned.
GRAPH_TABLES = (
    "access",
    "dataset",
    "evidence",
    "node",
    "revision",
)
RETAIN = (
    frozenset(ROOTS)
    | (frozenset(DEPENDENTS) - DERIVED)
    | {TYPES, "grow_wikidata_item"}
    | {f"{GRAPH}{name}" for name in GRAPH_TABLES}
)

# Missing public references must fail instead of silently changing catalogue
# semantics by dropping additional public songs or tree branches.
REFERENCES = (
    ("grow_criteria", "parent_id", "grow_criteria", "uuid"),
    ("grow_criteria", "root_id", "grow_criteria", "uuid"),
    ("grow_criteria", "type_id", TYPES, "id"),
    ("grow_criteria_playlist", "type_id", TYPES, "id"),
    (TRACK, "album_id", "grow_album", "uuid"),
    (TRACK, "genre_id", "grow_criteria", "uuid"),
    # Derived from Track.genre_id or the graph attribution (migration 0140). Its
    # derivation is verified after restore, not re-implemented here.
    ("grow_song", "genre_id", "grow_genre", "criteria_ptr_id"),
    ("grow_criteria", "graph_node_id", f"{GRAPH}node", "id"),
    (f"{TRACK}_playlist_rel", "genre_id", "grow_criteria", "uuid"),
)


def inventory(tsv: str) -> dict[str, list[tuple[str, str, str]]]:
    tables: dict[str, list[tuple[str, str, str]]] = {}
    for line in tsv.splitlines():
        fields = line.split("|")
        if len(fields) != 4:
            raise ValueError("invalid catalogue column inventory")
        table, column, data_type, nullable = fields
        matching(table, IDENTIFIER, "table")
        matching(column, IDENTIFIER, "column")
        if not data_type or nullable not in {"YES", "NO"}:
            raise ValueError("invalid catalogue column metadata")
        columns = tables.setdefault(table, [])
        if any(entry[0] == column for entry in columns):
            raise ValueError("duplicate catalogue column")
        columns.append((column, data_type, nullable))
    if not tables:
        raise ValueError("empty catalogue inventory")
    return tables


def verify_inventory(tsv: str) -> dict[str, list[tuple[str, str, str]]]:
    expected = inventory(SCHEMA.read_text())
    groups = (RETAIN, DERIVED, EMPTY, REBUILD)
    disjoint = sum(len(group) for group in groups) == len(RETAIN | DERIVED | EMPTY | REBUILD)
    if not disjoint or expected.keys() != RETAIN | DERIVED | EMPTY | REBUILD:
        raise ValueError("catalogue dispositions do not cover the exact reviewed schema")
    observed = inventory(tsv)
    if observed != expected:
        raise ValueError("catalogue schema drift: tables, ordered columns, types or nullability differ")
    return observed


def data_policy(tsv: str, schema_sql: bytes) -> Policy:
    """Record schema identity, which the executor must independently approve.

    Never treat hashing arbitrary bytes here as approval to execute schema SQL.
    """
    tables = verify_inventory(tsv)
    policy = Policy.parse(
        {
            "version": 1,
            "schema_sha256": hashlib.sha256(schema_sql).hexdigest(),
            "tables": {
                name: {
                    "columns": [entry[0] for entry in tables[name]],
                    "null_columns": [entry[0] for entry in tables[name] if entry[0] in {"user_id", "last_seen_run_id"}],
                    "minimum_rows": 30_000_000 if name in {TRACK, "grow_song"} else (1 if name == TYPES else 0),
                }
                for name in sorted(RETAIN | DERIVED)
            },
        }
    )
    return replace(policy, all_columns={name: tuple(entry[0] for entry in columns) for name, columns in tables.items()})


def _require_empty(table: str, predicate: str = "TRUE") -> str:
    # count(*) rather than EXISTS: EXISTS plans for the first row, and on tables
    # restored without statistics that picks a nested-loop anti join that never
    # finishes at catalogue scale. An aggregate needs every row, so it hashes.
    return (
        f'IF (SELECT count(*) FROM "public"."{table}" AS candidate WHERE {predicate}) > 0 THEN '
        f"RAISE EXCEPTION 'catalogue verification failed: {table}'; END IF;"
    )


def relation_inventory_sql() -> str:
    """Refuse missing, additional or non-table catalogue relations."""
    # information_schema.columns omits zero-column tables and materialized
    # views, and does not distinguish an updatable view from a base table.
    expected_tables = ",".join(sorted(RETAIN | DERIVED | EMPTY | REBUILD))
    # Staging tables are UNLOGGED; pg_dump skips their data, so only EMPTY ones
    # may be. An UNLOGGED retained table would silently lose its rows.
    unlogged_ok = ",".join(f"'{name}'" for name in sorted(EMPTY))
    return (
        "DO $$ DECLARE observed text; BEGIN SELECT string_agg(c.relname, ',' ORDER BY c.relname COLLATE \"C\") "
        "INTO observed FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='r' AND (c.relpersistence='p' "
        f"OR (c.relpersistence='u' AND c.relname IN ({unlogged_ok}))); "
        f"IF observed IS DISTINCT FROM '{expected_tables}' OR EXISTS "
        "(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND (c.relkind NOT IN ('r', 'i', 'S') "
        "OR (c.relkind='r' AND (c.relpersistence='t' "
        f"OR (c.relpersistence='u' AND c.relname NOT IN ({unlogged_ok})))))) THEN "
        "RAISE EXCEPTION 'catalogue relation inventory drift'; END IF; END $$;"
    )


def projection_sql(tsv: str) -> str:
    """Project data atomically, refusing private inventories and dangling keys.

    Denied and derived tables must already be empty. Apply reviewed post-data
    afterwards, and never expose this intermediate database to candidates.
    """
    verify_inventory(tsv)
    statements = ["BEGIN;", "SET LOCAL search_path = pg_catalog, pg_temp;"]
    # Check the actual connection too; supplied observations cannot establish
    # that this SQL is applied to the same database that was inspected.
    expected = "\n".join(SCHEMA.read_text().splitlines()).replace("'", "''")
    statements.append(
        "DO $$ DECLARE observed text; BEGIN SELECT string_agg("
        "table_name || '|' || column_name || '|' || data_type || '|' || is_nullable, "
        'chr(10) ORDER BY table_name COLLATE "C", ordinal_position) INTO observed '
        "FROM information_schema.columns WHERE table_schema='public'; "
        f"IF observed IS DISTINCT FROM '{expected}' THEN "
        "RAISE EXCEPTION 'catalogue schema drift on restore connection'; END IF; END $$;"
    )
    statements.append(relation_inventory_sql())
    statements.append(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND (c.relrowsecurity OR c.relforcerowsecurity)) OR EXISTS "
        "(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public') "
        "THEN RAISE EXCEPTION 'projection requires pre-data schema without triggers or RLS'; END IF; END $$;"
    )
    checks = [_require_empty(table) for table in sorted(EMPTY | REBUILD)]
    statements.append("DO $$ BEGIN " + " ".join(checks) + " END $$;")
    for table, predicates in (*ROOTS.items(), *DEPENDENTS.items()):
        for predicate in predicates:
            statements.append(f'DELETE FROM "public"."{table}" AS candidate WHERE {predicate};')
    # A public playlist referencing private criteria was removed above; prune
    # its parent and relationships again before any candidate can see names.
    statements.append(
        f'DELETE FROM "public"."{PLAYLIST}" AS candidate WHERE '
        f"{missing_reference('uuid', 'grow_criteria_playlist', 'playlist_id')};"
    )
    rel = f"{TRACK}_playlist_rel"
    statements.append(f'DELETE FROM "public"."{rel}" AS candidate WHERE {missing_reference("playlist_id", PLAYLIST)};')
    # This is an operational import reference, not catalogue content. Its
    # target table is intentionally absent from restored data.
    statements.append('UPDATE "public"."grow_genre" SET "last_seen_run_id" = NULL;')
    checks = [
        _require_empty(table, f'"{column}" IS NOT NULL AND {missing_reference(column, target, key)}')
        for table, column, target, key in REFERENCES
    ]
    checks.append(
        f'IF (SELECT count(*) FROM "public"."{rel}" AS candidate '
        f'JOIN "public"."{TRACK}" AS retained ON retained."uuid"=candidate."track_id" '
        'WHERE candidate."genre_id" IS DISTINCT FROM retained."genre_id") > 0 THEN '
        f"RAISE EXCEPTION 'catalogue verification failed: {rel}'; END IF;"
    )
    statements.append("DO $$ BEGIN " + " ".join(checks) + " END $$;")
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"
