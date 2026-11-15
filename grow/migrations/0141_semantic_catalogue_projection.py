"""Count effective direct assignments, reconstructing OLD membership after deletes."""

from importlib import import_module

from django.db import migrations

LEGACY = import_module("grow.migrations.0115_maintain_genre_catalogue_counts")
CACHE = LEGACY.CACHE
SOURCES = {
    "t": (LEGACY.TRACK, "uuid", ("uuid", "genre_id", "user_id")),
    "s": (LEGACY.SONG, "track_id", ("track_id",)),
    "a": ("the_music_tree_genre_kit_genregraphattribution", "id", ("track_id", "node_id")),
    "n": ("the_music_tree_genre_kit_genregraphnode", "id", ("dataset_id", "is_active")),
    "d": ("the_music_tree_genre_kit_genregraphdataset", "key", ("key",)),
    "c": ("grow_criteria", "uuid", ("uuid", "graph_node_id")),
}


def population(tables, affected):
    return f"""SELECT CASE WHEN EXISTS (SELECT 1 FROM {tables["d"]} d WHERE d.key = 'grow')
        THEN c.uuid ELSE t.genre_id END AS genre_id, COUNT(*) AS n
        FROM {tables["t"]} t JOIN {tables["s"]} s ON s.track_id = t.uuid
        LEFT JOIN ({tables["a"]} a JOIN {tables["n"]} node ON node.id = a.node_id
            AND node.dataset_id = 'grow' AND node.is_active) ON a.track_id = t.uuid
        LEFT JOIN {tables["c"]} c ON c.graph_node_id = a.node_id
        WHERE t.user_id IS NULL AND t.uuid IN ({affected}) GROUP BY 1"""


def affected_tracks(alias, rows):
    if alias in {"t", "s", "a"}:
        key = "uuid" if alias == "t" else "track_id"
        return " UNION ".join(f"SELECT {key} FROM {row}" for row in rows)
    if alias == "d":
        return f"SELECT track_id FROM {LEGACY.SONG}"
    node_ids = " UNION ".join(f"SELECT {'id' if alias == 'n' else 'graph_node_id'} FROM {row}" for row in rows)
    return f"SELECT track_id FROM {SOURCES['a'][0]} WHERE node_id IN ({node_ids})"


def statements(schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    tables = {alias: table for alias, (table, _, _) in SOURCES.items()}
    for alias, (table, key, relevant) in SOURCES.items():
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table} LIMIT 0")
            columns = [item[0] for item in cursor.description]
        column_list = ", ".join(f'"{col}"' for col in columns)
        for event in ("INSERT", "UPDATE", "DELETE"):
            refs, rows = [], []
            for label, available in (("old_rows", event != "INSERT"), ("new_rows", event != "DELETE")):
                if available:
                    marker = "OLD" if label == "old_rows" else "NEW"
                    if pg:
                        refs.append(f"{marker} TABLE AS {label}")
                        rows.append(label)
                    else:
                        rows.append("(SELECT " + ", ".join(f'{marker}."{col}" AS "{col}"' for col in columns) + ")")
            affected = affected_tracks(alias, rows)
            keys = " UNION ".join(f"SELECT {key} FROM {row}" for row in rows)
            before = dict(tables)
            before[alias] = f"(SELECT {column_list} FROM {table} WHERE {key} NOT IN ({keys})"
            if event != "INSERT":
                before[alias] += f" UNION ALL SELECT {column_list} FROM {rows[0]}"
            before[alias] += ")"
            old_query, new_query = population(before, affected), population(tables, affected)
            name = f"semantic_catalogue_{alias}_{event.lower()}"
            if pg:
                unchanged = (
                    "IF NOT EXISTS ("
                    + " UNION ALL ".join(f"SELECT 1 FROM {row}" for row in rows)
                    + ") THEN RETURN NULL; END IF;"
                )
                if alias == "d":
                    unchanged += (
                        "IF NOT EXISTS ("
                        + " UNION ALL ".join(f"SELECT 1 FROM {row} WHERE key = 'grow'" for row in rows)
                        + ") THEN RETURN NULL; END IF;"
                    )
                if event == "UPDATE":
                    differs = " OR ".join(f"o.{col} IS DISTINCT FROM n.{col}" for col in relevant)
                    unchanged += f"""IF NOT EXISTS (SELECT 1 FROM old_rows o FULL JOIN new_rows n USING ({key})
                        WHERE o.{key} IS NULL OR n.{key} IS NULL OR {differs}) THEN RETURN NULL; END IF;"""
                yield f"""CREATE FUNCTION {name}() RETURNS trigger AS $$
                    DECLARE changes jsonb;
                    BEGIN
                        {unchanged}
                        SELECT COALESCE(jsonb_agg(to_jsonb(d)), '[]'::jsonb) INTO changes FROM (
                            SELECT genre_id, SUM(n)::bigint AS n FROM (
                                SELECT genre_id, n FROM ({new_query}) additions
                                UNION ALL SELECT genre_id, -n FROM ({old_query}) removals
                            ) delta GROUP BY genre_id HAVING SUM(n) <> 0
                        ) d;
                        PERFORM apply_genre_catalogue_deltas(changes);
                        RETURN NULL;
                    END; $$ LANGUAGE plpgsql;
                    CREATE TRIGGER {name} AFTER {event} ON {table}
                    REFERENCING {" ".join(refs)} FOR EACH STATEMENT EXECUTE FUNCTION {name}();"""
            else:
                # SQLite serializes writers. Apply the net delta, rather than removing
                # and readding unchanged buckets (which can transiently underflow).
                delta = f"""SELECT genre_id, SUM(n) AS n FROM (
                    SELECT genre_id, n FROM ({new_query}) additions
                    UNION ALL SELECT genre_id, -n FROM ({old_query}) removals
                    ) GROUP BY genre_id HAVING SUM(n) <> 0"""
                when = ""
                if event == "UPDATE":
                    when = " WHEN (" + " OR ".join(f"OLD.{col} IS NOT NEW.{col}" for col in relevant) + ")"
                if alias == "d":
                    markers = (["OLD"] if event != "INSERT" else []) + (["NEW"] if event != "DELETE" else [])
                    guard = "(" + " OR ".join(f"{marker}.key = 'grow'" for marker in markers) + ")"
                    when += (" AND " if when else " WHEN ") + guard
                yield f"""CREATE TRIGGER {name} AFTER {event} ON {table}{when} BEGIN
                    SELECT CASE WHEN EXISTS (SELECT 1 FROM ({delta}) d
                        LEFT JOIN {CACHE} b ON b.genre_id IS d.genre_id
                        WHERE d.n < 0 AND (b.id IS NULL OR b.tracks_count + d.n < 0))
                        THEN RAISE(ABORT, 'Genre catalogue count underflow') END;
                    UPDATE {CACHE} SET tracks_count = tracks_count + COALESCE((
                        SELECT d.n FROM ({delta}) d WHERE d.genre_id IS {CACHE}.genre_id), 0);
                    INSERT INTO {CACHE} (genre_id, tracks_count) SELECT genre_id, n FROM ({delta}) d
                        WHERE n > 0 AND NOT EXISTS (SELECT 1 FROM {CACHE} b WHERE b.genre_id IS d.genre_id);
                    DELETE FROM {CACHE} WHERE tracks_count = 0;
                    UPDATE grow_genre_tree_version SET token = lower(hex(randomblob(16))) WHERE id = 1
                        AND EXISTS (SELECT 1 FROM ({delta}));
                END"""


def backwards(apps, schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    for alias, (table, _, _) in SOURCES.items():
        for event in ("insert", "update", "delete"):
            name = f"semantic_catalogue_{alias}_{event}"
            schema_editor.execute(f"DROP TRIGGER {name}" + (f" ON {table}" if pg else ""))
            if pg:
                schema_editor.execute(f"DROP FUNCTION {name}()")
    if pg:
        for alias in ("a", "n", "d", "c"):
            schema_editor.execute(f"DROP TRIGGER semantic_catalogue_source_gate ON {SOURCES[alias][0]}")
        for alias in ("a", "n", "d", "c"):
            schema_editor.execute(f"DROP TRIGGER semantic_catalogue_truncate ON {SOURCES[alias][0]}")
    LEGACY.drop(apps, schema_editor)
    schema_editor.execute(f"DELETE FROM {CACHE}")
    LEGACY.create(apps, schema_editor)


def forwards(apps, schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    if not pg and schema_editor.connection.vendor != "sqlite":
        raise NotImplementedError("Semantic catalogue counts require PostgreSQL or SQLite")
    if pg:
        tables = sorted({table for table, _, _ in SOURCES.values()} | {CACHE})
        schema_editor.execute(f"LOCK TABLE {', '.join(tables)} IN ACCESS EXCLUSIVE MODE NOWAIT")
        schema_editor.execute("""DO $$ BEGIN
            IF NOT pg_try_advisory_xact_lock(716731928417) THEN
                RAISE EXCEPTION 'Catalogue source gate is busy; retry migration';
            END IF;
        END $$""")
    for alias in ("t", "s"):
        table = SOURCES[alias][0]
        for event in ("insert", "update", "delete"):
            name = f"genre_catalogue_{alias}_{event}"
            schema_editor.execute(f"DROP TRIGGER {name}" + (f" ON {table}" if pg else ""))
            if pg:
                schema_editor.execute(f"DROP FUNCTION {name}()")
    for statement in statements(schema_editor):
        schema_editor.execute(statement)
    if pg:
        # Existing TRUNCATE triggers call this function after clearing their table.
        schema_editor.execute("""CREATE OR REPLACE FUNCTION rebuild_genre_catalogue_counts() RETURNS trigger AS $$
            BEGIN
                DELETE FROM grow_genre_catalogue_count;
                INSERT INTO grow_genre_catalogue_count (genre_id, tracks_count)
                    SELECT m.genre_id, COUNT(*) FROM grow_song_membership m
                    JOIN grow_song s ON s.track_id = m.track_id
                    JOIN the_music_tree_genre_kit_track t ON t.uuid = m.track_id
                    WHERE t.user_id IS NULL GROUP BY m.genre_id;
                UPDATE grow_genre_tree_version SET token = gen_random_uuid() WHERE id = 1;
                RETURN NULL;
            END; $$ LANGUAGE plpgsql""")
    if pg:
        for alias in ("a", "n", "d", "c"):
            events = "TRUNCATE" if alias == "a" else "INSERT OR UPDATE OR DELETE OR TRUNCATE"
            schema_editor.execute(f"""CREATE TRIGGER semantic_catalogue_source_gate
                BEFORE {events} ON {SOURCES[alias][0]}
                FOR EACH STATEMENT EXECUTE FUNCTION grow_assignment_source_gate()""")
        for alias in ("a", "n", "d", "c"):
            schema_editor.execute(f"""CREATE TRIGGER semantic_catalogue_truncate
                AFTER TRUNCATE ON {SOURCES[alias][0]} FOR EACH STATEMENT
                EXECUTE FUNCTION rebuild_genre_catalogue_counts()""")
    schema_editor.execute(f"DELETE FROM {CACHE}")
    schema_editor.execute(f"""INSERT INTO {CACHE} (genre_id, tracks_count)
        SELECT m.genre_id, COUNT(*) FROM grow_song_membership m
        JOIN {LEGACY.SONG} s ON s.track_id = m.track_id JOIN {LEGACY.TRACK} t ON t.uuid = m.track_id
        WHERE t.user_id IS NULL GROUP BY m.genre_id""")


class Migration(migrations.Migration):
    dependencies = [("grow", "0140_song_membership_boundary")]
    operations = [migrations.RunPython(forwards, backwards)]
