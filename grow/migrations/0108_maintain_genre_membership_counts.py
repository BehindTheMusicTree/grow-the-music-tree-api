from django.db import migrations

REL = "the_music_tree_genre_kit_track_playlist_rel"
TRACK = "the_music_tree_genre_kit_track"
PLAYLIST = "the_music_tree_genre_kit_playlist"
CRITERIA_PLAYLIST = "grow_criteria_playlist"
CACHE = "grow_genre_membership_count"
SOURCES = {"r": REL, "t": TRACK, "p": PLAYLIST, "c": CRITERIA_PLAYLIST}
# Acquire a transaction gate before changing source rows. Otherwise a concurrent
# track move and membership insertion can each aggregate the other's old state.
GATED_TABLES = (
    *SOURCES.values(),
    "grow_criteria",
    "grow_criteria_additional_primary_parents",
    "grow_criteria_secondary_parents",
    "grow_genre",
    "the_music_tree_genre_kit_criteriatype",
)


def source_query(alias=None, replacement=None, predicate="TRUE"):
    tables = {key: replacement if key == alias else table for key, table in SOURCES.items()}
    return f"""
        SELECT r.playlist_id, t.genre_id, COUNT(*) AS n
        FROM {tables["r"]} r
        JOIN {tables["t"]} t ON t.uuid = r.track_id
        JOIN {tables["p"]} p ON p.uuid = r.playlist_id
        JOIN {tables["c"]} c ON c.playlist_id = p.uuid
        WHERE r.user_id IS NULL AND t.user_id IS NULL AND p.user_id IS NULL
          AND c.type_id = 0 AND ({predicate})
        GROUP BY r.playlist_id, t.genre_id
    """


APPLY_DELTAS = f"""
CREATE FUNCTION apply_genre_membership_deltas(changes jsonb) RETURNS void AS $$
BEGIN
    IF changes = '[]'::jsonb THEN RETURN; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_to_recordset(changes) AS d(playlist_id uuid, genre_id uuid, n bigint)
        LEFT JOIN {CACHE} b ON b.playlist_id = d.playlist_id AND b.genre_id IS NOT DISTINCT FROM d.genre_id
        WHERE d.n < 0 AND (b.id IS NULL OR b.tracks_count + d.n < 0)
    ) THEN
        RAISE EXCEPTION 'Genre membership count underflow; verify and repair the projection';
    END IF;
    UPDATE {CACHE} b SET tracks_count = b.tracks_count + d.n
    FROM jsonb_to_recordset(changes) AS d(playlist_id uuid, genre_id uuid, n bigint)
    WHERE b.playlist_id = d.playlist_id AND b.genre_id IS NOT DISTINCT FROM d.genre_id;
    INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count)
    SELECT d.playlist_id, d.genre_id, d.n
    FROM jsonb_to_recordset(changes) AS d(playlist_id uuid, genre_id uuid, n bigint)
    WHERE d.n > 0 AND NOT EXISTS (
        SELECT 1 FROM {CACHE} b
        WHERE b.playlist_id = d.playlist_id AND b.genre_id IS NOT DISTINCT FROM d.genre_id
    );
    DELETE FROM {CACHE} WHERE tracks_count = 0;
END;
$$ LANGUAGE plpgsql;
"""

GATE = """
CREATE FUNCTION lock_genre_membership_sources() RETURNS trigger AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Genre membership writes require READ COMMITTED isolation';
    END IF;
    -- Independent of rows so TRUNCATE/flush can empty the source tables and version
    -- singleton in any order. All writers take this before the legacy version-row lock.
    PERFORM pg_advisory_xact_lock(716731928417);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


def postgres_statements():
    yield GATE
    yield APPLY_DELTAS
    for table in GATED_TABLES:
        update = "UPDATE"
        if table == TRACK:
            update = "UPDATE OF uuid, genre_id, user_id"
        elif table == PLAYLIST:
            update = "UPDATE OF uuid, created_on, updated_on, user_id"
        yield (
            f"CREATE TRIGGER lock_genre_membership_sources BEFORE INSERT OR {update} OR DELETE OR TRUNCATE "
            f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION lock_genre_membership_sources()"
        )
    for alias, table in SOURCES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            parts = []
            references = []
            if event != "DELETE":
                parts.append(f"SELECT playlist_id, genre_id, n FROM ({source_query(alias, 'new_rows')}) additions")
                references.append("NEW TABLE AS new_rows")
            if event != "INSERT":
                parts.append(f"SELECT playlist_id, genre_id, -n AS n FROM ({source_query(alias, 'old_rows')}) removals")
                references.append("OLD TABLE AS old_rows")
            name = f"genre_membership_{alias}_{event.lower()}"
            unchanged = ""
            if event == "UPDATE":
                keys = {"r": "id", "t": "uuid", "p": "uuid", "c": "playlist_id"}
                columns = {
                    "r": ("playlist_id", "track_id", "user_id"),
                    "t": ("genre_id", "user_id"),
                    "p": ("user_id",),
                    "c": ("type_id",),
                }[alias]
                differs = " OR ".join(f"o.{col} IS DISTINCT FROM n.{col}" for col in columns)
                key = keys[alias]
                unchanged = f"""
                    IF NOT EXISTS (SELECT 1 FROM old_rows o FULL JOIN new_rows n USING ({key})
                        WHERE o.{key} IS NULL OR n.{key} IS NULL OR {differs}) THEN RETURN NULL; END IF;
                """
            yield f"""
                CREATE FUNCTION {name}() RETURNS trigger AS $$
                DECLARE changes jsonb;
                BEGIN
                    {unchanged}
                    SELECT COALESCE(jsonb_agg(to_jsonb(d)), '[]'::jsonb) INTO changes FROM (
                        SELECT playlist_id, genre_id, SUM(n)::bigint AS n
                        FROM ({" UNION ALL ".join(parts)}) changes
                        GROUP BY playlist_id, genre_id HAVING SUM(n) <> 0
                    ) d;
                    PERFORM apply_genre_membership_deltas(changes);
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER {name} AFTER {event} ON {table}
                REFERENCING {" ".join(references)} FOR EACH STATEMENT EXECUTE FUNCTION {name}();
            """
    # TRUNCATE can remove any part of the source graph. A full rebuild is rare and
    # avoids depending on the order PostgreSQL fires cascaded truncate triggers.
    yield f"""
        CREATE FUNCTION rebuild_genre_membership_counts() RETURNS trigger AS $$
        BEGIN
            DELETE FROM {CACHE};
            INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count) {source_query()};
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """
    for table in SOURCES.values():
        yield (
            f"CREATE TRIGGER rebuild_genre_membership_counts AFTER TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION rebuild_genre_membership_counts()"
        )


def sqlite_statements():
    # SQLite serializes writers and supports row triggers only. Project each changed
    # source row through the same joins as PostgreSQL's statement transition tables.
    keys = {"r": "id", "t": "uuid", "p": "uuid", "c": "playlist_id"}
    for alias, table in SOURCES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            statements = []
            for row, sign in (("OLD", -1), ("NEW", 1)):
                if (event == "INSERT" and row == "OLD") or (event == "DELETE" and row == "NEW"):
                    continue
                # OLD/NEW are records, so construct a one-row source relation explicitly.
                columns = {
                    "r": ("id", "playlist_id", "track_id", "user_id"),
                    "t": ("uuid", "genre_id", "user_id"),
                    "p": ("uuid", "user_id"),
                    "c": ("playlist_id", "type_id"),
                }[alias]
                replacement = "(SELECT " + ", ".join(f"{row}.{col} AS {col}" for col in columns) + ")"
                query = source_query(alias, replacement)
                if sign < 0:
                    statements.append(f"""
                        SELECT CASE WHEN EXISTS (
                            SELECT 1 FROM ({query}) d LEFT JOIN {CACHE} b
                            ON b.playlist_id = d.playlist_id AND b.genre_id IS d.genre_id
                            WHERE b.id IS NULL OR b.tracks_count < d.n
                        ) THEN RAISE(ABORT, 'Genre membership count underflow') END;
                        UPDATE {CACHE} SET tracks_count = tracks_count - COALESCE((
                            SELECT d.n FROM ({query}) d WHERE d.playlist_id = {CACHE}.playlist_id
                            AND d.genre_id IS {CACHE}.genre_id
                        ), 0);
                        DELETE FROM {CACHE} WHERE tracks_count = 0;
                    """)
                else:
                    for condition, conflict in (
                        ("genre_id IS NOT NULL", "playlist_id, genre_id"),
                        ("genre_id IS NULL", "playlist_id"),
                    ):
                        statements.append(f"""
                            INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count)
                            SELECT playlist_id, genre_id, n FROM ({query}) d WHERE {condition}
                            ON CONFLICT ({conflict}) WHERE {condition}
                            DO UPDATE SET tracks_count = tracks_count + excluded.tracks_count;
                        """)
            # A no-op update cannot change a bucket, and skipping it also avoids
            # temporarily deleting/recreating buckets during position/view updates.
            relevant = {
                "r": ("playlist_id", "track_id", "user_id"),
                "t": ("genre_id", "user_id"),
                "p": ("user_id",),
                "c": ("type_id",),
            }[alias]
            when = (
                " WHEN " + " OR ".join(f"OLD.{col} IS NOT NEW.{col}" for col in relevant) if event == "UPDATE" else ""
            )
            yield (
                f"CREATE TRIGGER genre_membership_{alias}_{event.lower()} AFTER {event} ON {table}{when} "
                f"BEGIN {' '.join(statements)} END;"
            )


def create(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        statements = postgres_statements()
    elif vendor == "sqlite":
        statements = sqlite_statements()
    else:
        raise NotImplementedError(f"No genre membership count triggers for {vendor}")
    for statement in statements:
        schema_editor.execute(statement)
    schema_editor.execute(f"DELETE FROM {CACHE}")
    schema_editor.execute(f"INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count) {source_query()}")


def drop(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    for alias, table in SOURCES.items():
        for event in ("insert", "update", "delete"):
            name = f"genre_membership_{alias}_{event}"
            if vendor == "postgresql":
                schema_editor.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                schema_editor.execute(f"DROP FUNCTION IF EXISTS {name}()")
            elif vendor == "sqlite":
                schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")
            else:
                raise NotImplementedError(f"No genre membership count triggers for {vendor}")
        if vendor == "postgresql":
            schema_editor.execute(f"DROP TRIGGER IF EXISTS rebuild_genre_membership_counts ON {table}")
    if vendor == "postgresql":
        for table in GATED_TABLES:
            schema_editor.execute(f"DROP TRIGGER IF EXISTS lock_genre_membership_sources ON {table}")
        for function in (
            "rebuild_genre_membership_counts()",
            "apply_genre_membership_deltas(jsonb)",
            "lock_genre_membership_sources()",
        ):
            schema_editor.execute(f"DROP FUNCTION IF EXISTS {function}")


class Migration(migrations.Migration):
    dependencies = [("grow", "0107_genre_membership_counts")]
    operations = [migrations.RunPython(create, drop)]
