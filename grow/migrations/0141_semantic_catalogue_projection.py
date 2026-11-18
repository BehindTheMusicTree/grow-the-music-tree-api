"""Count catalogue songs per `grow_song.genre_id`, the materialised effective genre."""

from importlib import import_module

from django.db import migrations

LEGACY = import_module("grow.migrations.0115_maintain_genre_catalogue_counts")
CACHE, TRACK, SONG = LEGACY.CACHE, LEGACY.TRACK, LEGACY.SONG
SOURCES = {"t": TRACK, "s": SONG}
# Columns whose change can move a song between buckets, per source table.
RELEVANT = {"t": ("uuid", "user_id"), "s": ("track_id", "genre_id")}
KEYS = {"t": "uuid", "s": "track_id"}


def source_query(alias=None, replacement=None):
    tables = {key: replacement if key == alias else table for key, table in SOURCES.items()}
    return f"""SELECT s.genre_id, COUNT(*) AS n FROM {tables["t"]} t
        JOIN {tables["s"]} s ON s.track_id = t.uuid
        WHERE t.user_id IS NULL GROUP BY s.genre_id"""


def postgres_statements():
    yield (
        "CREATE TRIGGER lock_genre_membership_sources BEFORE INSERT OR UPDATE OF track_id, genre_id OR DELETE "
        f"OR TRUNCATE ON {SONG} FOR EACH STATEMENT EXECUTE FUNCTION lock_genre_membership_sources()"
    )
    yield LEGACY.APPLY_DELTAS
    for alias, table in SOURCES.items():
        key = KEYS[alias]
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
                differs = " OR ".join(f"o.{col} IS DISTINCT FROM n.{col}" for col in RELEVANT[alias])
                unchanged = f"""IF NOT EXISTS (SELECT 1 FROM old_rows o FULL JOIN new_rows n USING ({key})
                    WHERE o.{key} IS NULL OR n.{key} IS NULL OR {differs})
                    THEN RETURN NULL; END IF;"""
            yield f"""
                CREATE FUNCTION {name}() RETURNS trigger AS $$
                DECLARE changes jsonb;
                BEGIN
                    {unchanged}
                    SELECT COALESCE(jsonb_agg(to_jsonb(d)), '[]'::jsonb) INTO changes FROM (
                        SELECT genre_id, SUM(n)::bigint AS n FROM ({" UNION ALL ".join(parts)}) changes
                        GROUP BY genre_id HAVING SUM(n) <> 0
                    ) d;
                    PERFORM apply_genre_catalogue_deltas(changes);
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER {name} AFTER {event} ON {table}
                REFERENCING {" ".join(references)} FOR EACH STATEMENT EXECUTE FUNCTION {name}();
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
        yield (
            f"CREATE TRIGGER rebuild_genre_catalogue_counts AFTER TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION rebuild_genre_catalogue_counts()"
        )


def sqlite_statements():
    for alias, table in SOURCES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            statements = []
            for row, sign in (("OLD", -1), ("NEW", 1)):
                if (event == "INSERT" and row == "OLD") or (event == "DELETE" and row == "NEW"):
                    continue
                columns = ("uuid", "user_id") if alias == "t" else ("track_id", "genre_id")
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
                    statements.append(f"""
                        UPDATE {CACHE} SET tracks_count = tracks_count + COALESCE((
                            SELECT d.n FROM ({query}) d WHERE d.genre_id IS {CACHE}.genre_id
                        ), 0);
                        INSERT INTO {CACHE} (genre_id, tracks_count)
                        SELECT genre_id, n FROM ({query}) d WHERE NOT EXISTS (
                            SELECT 1 FROM {CACHE} b WHERE b.genre_id IS d.genre_id
                        );
                    """)
            when = ""
            if event == "UPDATE":
                when = " WHEN " + " OR ".join(f"OLD.{col} IS NOT NEW.{col}" for col in RELEVANT[alias])
            statements.append("UPDATE grow_genre_tree_version SET token = lower(hex(randomblob(16))) WHERE id = 1;")
            yield (
                f"CREATE TRIGGER genre_catalogue_{alias}_{event.lower()} AFTER {event} ON {table}{when} "
                f"BEGIN {' '.join(statements)} END;"
            )


def forwards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor not in {"postgresql", "sqlite"}:
        raise NotImplementedError("Catalogue counts require PostgreSQL or SQLite")
    LEGACY.drop(apps, schema_editor)
    statements = postgres_statements() if vendor == "postgresql" else sqlite_statements()
    for statement in statements:
        schema_editor.execute(statement)
    schema_editor.execute(f"DELETE FROM {CACHE}")
    schema_editor.execute(f"INSERT INTO {CACHE} (genre_id, tracks_count) {source_query()}")


def backwards(apps, schema_editor):
    LEGACY.drop(apps, schema_editor)
    schema_editor.execute(f"DELETE FROM {CACHE}")
    LEGACY.create(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("grow", "0140_song_membership_boundary")]
    operations = [migrations.RunPython(forwards, backwards)]
