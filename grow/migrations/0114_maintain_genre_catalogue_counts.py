from django.db import migrations

TRACK = "the_music_tree_genre_kit_track"
SONG = "grow_song"
CACHE = "grow_genre_catalogue_count"
SOURCES = {"t": TRACK, "s": SONG}
# Relation locks precede the gate, including relations an old writer may have
# locked before reaching its BEFORE trigger. NOWAIT makes a busy migration retryable.
LOCKED_TABLES = (
    "the_music_tree_genre_kit_track_playlist_rel", TRACK,
    "the_music_tree_genre_kit_playlist", "grow_criteria_playlist", "grow_criteria",
    "grow_criteria_additional_primary_parents", "grow_criteria_secondary_parents",
    "grow_genre", "the_music_tree_genre_kit_criteriatype", SONG,
)


def source_query(alias=None, replacement=None):
    tables = {key: replacement if key == alias else table for key, table in SOURCES.items()}
    return f"""SELECT t.genre_id, COUNT(*) AS n FROM {tables['t']} t
        JOIN {tables['s']} s ON s.track_id = t.uuid
        WHERE t.user_id IS NULL GROUP BY t.genre_id"""


APPLY_DELTAS = f"""
CREATE FUNCTION apply_genre_catalogue_deltas(changes jsonb) RETURNS void AS $$
BEGIN
    IF changes = '[]'::jsonb THEN RETURN; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_to_recordset(changes) AS d(genre_id uuid, n bigint)
        LEFT JOIN {CACHE} b ON b.genre_id IS NOT DISTINCT FROM d.genre_id
        WHERE d.n < 0 AND (b.id IS NULL OR b.tracks_count + d.n < 0)
    ) THEN RAISE EXCEPTION 'Genre catalogue count underflow; verify and repair the projection'; END IF;
    UPDATE {CACHE} b SET tracks_count = b.tracks_count + d.n
    FROM jsonb_to_recordset(changes) AS d(genre_id uuid, n bigint)
    WHERE b.genre_id IS NOT DISTINCT FROM d.genre_id;
    INSERT INTO {CACHE} (genre_id, tracks_count)
    SELECT d.genre_id, d.n FROM jsonb_to_recordset(changes) AS d(genre_id uuid, n bigint)
    WHERE d.n > 0 AND NOT EXISTS (
        SELECT 1 FROM {CACHE} b WHERE b.genre_id IS NOT DISTINCT FROM d.genre_id
    );
    DELETE FROM {CACHE} WHERE tracks_count = 0;
    UPDATE grow_genre_tree_version SET token = gen_random_uuid() WHERE id = 1;
END;
$$ LANGUAGE plpgsql;
"""


def postgres_statements():
    yield (f"CREATE TRIGGER lock_genre_membership_sources BEFORE INSERT OR UPDATE OF track_id OR DELETE OR TRUNCATE "
           f"ON {SONG} FOR EACH STATEMENT EXECUTE FUNCTION lock_genre_membership_sources()")
    yield APPLY_DELTAS
    for alias, table in SOURCES.items():
        key = "uuid" if alias == "t" else "track_id"
        for event in ("INSERT", "UPDATE", "DELETE"):
            references, parts = [], []
            if event != "DELETE":
                references.append("NEW TABLE AS new_rows")
                parts.append(f"SELECT genre_id, n FROM ({source_query(alias, 'new_rows')}) additions")
            if event != "INSERT":
                references.append("OLD TABLE AS old_rows")
                parts.append(f"SELECT genre_id, -n AS n FROM ({source_query(alias, 'old_rows')}) removals")
            name = f"genre_catalogue_{alias}_{event.lower()}"
            unchanged = ""
            if event == "UPDATE":
                relevant = ("genre_id", "user_id") if alias == "t" else ()
                differs = " OR ".join(f"o.{col} IS DISTINCT FROM n.{col}" for col in relevant)
                unchanged = f"""IF NOT EXISTS (SELECT 1 FROM old_rows o FULL JOIN new_rows n USING ({key})
                    WHERE o.{key} IS NULL OR n.{key} IS NULL {('OR ' + differs) if differs else ''})
                    THEN RETURN NULL; END IF;"""
            yield f"""
                CREATE FUNCTION {name}() RETURNS trigger AS $$
                DECLARE changes jsonb;
                BEGIN
                    {unchanged}
                    SELECT COALESCE(jsonb_agg(to_jsonb(d)), '[]'::jsonb) INTO changes FROM (
                        SELECT genre_id, SUM(n)::bigint AS n FROM ({' UNION ALL '.join(parts)}) changes
                        GROUP BY genre_id HAVING SUM(n) <> 0
                    ) d;
                    PERFORM apply_genre_catalogue_deltas(changes);
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER {name} AFTER {event} ON {table}
                REFERENCING {' '.join(references)} FOR EACH STATEMENT EXECUTE FUNCTION {name}();
            """
    yield f"""
        CREATE FUNCTION rebuild_genre_catalogue_counts() RETURNS trigger AS $$
        BEGIN
            DELETE FROM {CACHE};
            INSERT INTO {CACHE} (genre_id, tracks_count) {source_query()};
            UPDATE grow_genre_tree_version SET token = gen_random_uuid() WHERE id = 1;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """
    for table in SOURCES.values():
        yield (f"CREATE TRIGGER rebuild_genre_catalogue_counts AFTER TRUNCATE ON {table} "
               "FOR EACH STATEMENT EXECUTE FUNCTION rebuild_genre_catalogue_counts()")


def sqlite_statements():
    for alias, table in SOURCES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            statements = []
            for row, sign in (("OLD", -1), ("NEW", 1)):
                if (event == "INSERT" and row == "OLD") or (event == "DELETE" and row == "NEW"):
                    continue
                columns = ("uuid", "genre_id", "user_id") if alias == "t" else ("track_id",)
                replacement = "(SELECT " + ", ".join(f"{row}.{col} AS {col}" for col in columns) + ")"
                query = source_query(alias, replacement)
                if sign < 0:
                    statements.append(f"""
                        SELECT CASE WHEN EXISTS (
                            SELECT 1 FROM ({query}) d LEFT JOIN {CACHE} b ON b.genre_id IS d.genre_id
                            WHERE b.id IS NULL OR b.tracks_count < d.n
                        ) THEN RAISE(ABORT, 'Genre catalogue count underflow') END;
                        UPDATE {CACHE} SET tracks_count = tracks_count - COALESCE((
                            SELECT d.n FROM ({query}) d WHERE d.genre_id IS {CACHE}.genre_id
                        ), 0);
                        DELETE FROM {CACHE} WHERE tracks_count = 0;
                    """)
                else:
                    # Partial expression uniqueness for the null bucket is enforced by
                    # the index; SQLite's single writer makes this update/insert atomic.
                    statements.append(f"""
                        UPDATE {CACHE} SET tracks_count = tracks_count + COALESCE((
                            SELECT d.n FROM ({query}) d WHERE d.genre_id IS {CACHE}.genre_id
                        ), 0);
                        INSERT INTO {CACHE} (genre_id, tracks_count)
                        SELECT genre_id, n FROM ({query}) d WHERE NOT EXISTS (
                            SELECT 1 FROM {CACHE} b WHERE b.genre_id IS d.genre_id
                        );
                    """)
            relevant = ("uuid", "genre_id", "user_id") if alias == "t" else ("track_id",)
            when = " WHEN " + " OR ".join(f"OLD.{col} IS NOT NEW.{col}" for col in relevant) if event == "UPDATE" else ""
            statements.append("UPDATE grow_genre_tree_version SET token = lower(hex(randomblob(16))) WHERE id = 1;")
            yield (f"CREATE TRIGGER genre_catalogue_{alias}_{event.lower()} AFTER {event} ON {table}{when} "
                   f"BEGIN {' '.join(statements)} END;")


def create(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(f"LOCK TABLE {', '.join(LOCKED_TABLES)} IN ACCESS EXCLUSIVE MODE NOWAIT")
        schema_editor.execute("""DO $$ BEGIN
            IF NOT pg_try_advisory_xact_lock(716731928417) THEN
                RAISE EXCEPTION 'Catalogue migration source gate is busy; retry the migration';
            END IF;
        END $$""")
        statements = postgres_statements()
    elif vendor == "sqlite":
        statements = sqlite_statements()
    else:
        raise NotImplementedError(f"No genre catalogue count triggers for {vendor}")
    for statement in statements:
        schema_editor.execute(statement)
    schema_editor.execute(f"INSERT INTO {CACHE} (genre_id, tracks_count) {source_query()}")


def drop(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    for alias, table in SOURCES.items():
        for event in ("insert", "update", "delete"):
            name = f"genre_catalogue_{alias}_{event}"
            if vendor == "postgresql":
                schema_editor.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                schema_editor.execute(f"DROP FUNCTION IF EXISTS {name}()")
            elif vendor == "sqlite":
                schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")
            else:
                raise NotImplementedError(f"No genre catalogue count triggers for {vendor}")
        if vendor == "postgresql":
            schema_editor.execute(f"DROP TRIGGER IF EXISTS rebuild_genre_catalogue_counts ON {table}")
    if vendor == "postgresql":
        schema_editor.execute(f"DROP TRIGGER IF EXISTS lock_genre_membership_sources ON {SONG}")
        schema_editor.execute("DROP FUNCTION IF EXISTS rebuild_genre_catalogue_counts()")
        schema_editor.execute("DROP FUNCTION IF EXISTS apply_genre_catalogue_deltas(jsonb)")


class Migration(migrations.Migration):
    dependencies = [("grow", "0113_genre_catalogue_counts")]
    operations = [migrations.RunPython(create, drop)]
