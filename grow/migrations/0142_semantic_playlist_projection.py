"""Derive playlist membership buckets and `TrackPlaylistRel.genre_id` from effective song membership.

Without a `grow` dataset the effective genre is `Track.genre_id`, so existing rows and counts are unchanged.
"""

from importlib import import_module

from django.db import migrations, transaction

BUCKETS = import_module("grow.migrations.0108_maintain_genre_membership_counts")
REL_SYNC = import_module("grow.migrations.0118_maintain_track_playlist_rel_genre")
CACHE = BUCKETS.CACHE
REL = BUCKETS.REL
VIEW = "grow_song_membership"
BATCH = REL_SYNC.BATCH
LOCK_KEY = 716731928417
# alias: (table, key, columns whose change can alter a bucket)
SOURCES = {
    "r": (REL, "id", ("playlist_id", "track_id", "user_id")),
    "t": (BUCKETS.TRACK, "uuid", ("uuid", "genre_id", "user_id")),
    "p": (BUCKETS.PLAYLIST, "uuid", ("uuid", "user_id")),
    "k": (BUCKETS.CRITERIA_PLAYLIST, "playlist_id", ("playlist_id", "type_id")),
    "a": ("the_music_tree_genre_kit_genregraphattribution", "id", ("track_id", "node_id")),
    "n": ("the_music_tree_genre_kit_genregraphnode", "id", ("dataset_id", "is_active")),
    "d": ("the_music_tree_genre_kit_genregraphdataset", "key", ("key",)),
    "c": ("grow_criteria", "uuid", ("uuid", "graph_node_id")),
}
# Sources that can change a track's effective genre, hence its memberships' denormalised genre.
GENRE_SOURCES = {"t", "a", "n", "d", "c"}


def scope(alias, rows, target):
    """Restrict a population to the memberships a changed row can affect."""

    def keys(column):
        return " UNION ".join(f"SELECT {column} FROM {row}" for row in rows)

    by_track = {"r": "track_id", "t": "uuid", "a": "track_id"}
    by_playlist = {"p": "uuid", "k": "playlist_id"}
    if alias in by_track:
        return f"{target}.track_id IN ({keys(by_track[alias])})"
    if alias in by_playlist:
        return f"{target}.playlist_id IN ({keys(by_playlist[alias])})"
    if alias == "d":
        return "1 = 1"
    attribution = SOURCES["a"][0]
    node_ids = keys("id" if alias == "n" else "graph_node_id")
    return f"{target}.track_id IN (SELECT track_id FROM {attribution} WHERE node_id IN ({node_ids}))"


def population(tables, predicate):
    return f"""SELECT r.playlist_id, CASE WHEN EXISTS (SELECT 1 FROM {tables["d"]} dd WHERE dd.key = 'grow')
        THEN c.uuid ELSE t.genre_id END AS genre_id, COUNT(*) AS n
        FROM {tables["r"]} r JOIN {tables["t"]} t ON t.uuid = r.track_id
        JOIN {tables["p"]} p ON p.uuid = r.playlist_id JOIN {tables["k"]} k ON k.playlist_id = p.uuid
        LEFT JOIN ({tables["a"]} a JOIN {tables["n"]} node ON node.id = a.node_id
            AND node.dataset_id = 'grow' AND node.is_active) ON a.track_id = t.uuid
        LEFT JOIN {tables["c"]} c ON c.graph_node_id = a.node_id
        WHERE r.user_id IS NULL AND t.user_id IS NULL AND p.user_id IS NULL AND k.type_id = 0
          AND ({predicate}) GROUP BY 1, 2"""


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
            row_keys = " UNION ".join(f"SELECT {key} FROM {row}" for row in rows)
            before = dict(tables)
            before[alias] = f"(SELECT {column_list} FROM {table} WHERE {key} NOT IN ({row_keys})"
            if event != "INSERT":
                before[alias] += f" UNION ALL SELECT {column_list} FROM {rows[0]}"
            before[alias] += ")"
            predicate = scope(alias, rows, "r")
            old_query, new_query = population(before, predicate), population(tables, predicate)
            name = f"semantic_membership_{alias}_{event.lower()}"
            if pg:
                unchanged = (
                    "IF NOT EXISTS (" + " UNION ALL ".join(f"SELECT 1 FROM {row}" for row in rows) + ") "
                    "THEN RETURN NULL; END IF;"
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
                sync = ""
                if alias in GENRE_SOURCES:
                    sync = f"""UPDATE {REL} r SET genre_id = m.genre_id FROM {VIEW} m
                        WHERE m.track_id = r.track_id AND {predicate} AND r.genre_id IS DISTINCT FROM m.genre_id;"""
                yield f"""CREATE FUNCTION {name}() RETURNS trigger AS $$
                    DECLARE changes jsonb;
                    BEGIN
                        {unchanged}
                        SELECT COALESCE(jsonb_agg(to_jsonb(d)), '[]'::jsonb) INTO changes FROM (
                            SELECT playlist_id, genre_id, SUM(n)::bigint AS n FROM (
                                SELECT playlist_id, genre_id, n FROM ({new_query}) additions
                                UNION ALL SELECT playlist_id, genre_id, -n FROM ({old_query}) removals
                            ) delta GROUP BY playlist_id, genre_id HAVING SUM(n) <> 0
                        ) d;
                        PERFORM apply_genre_membership_deltas(changes);
                        {sync}
                        RETURN NULL;
                    END; $$ LANGUAGE plpgsql;
                    CREATE TRIGGER {name} AFTER {event} ON {table}
                    REFERENCING {" ".join(refs)} FOR EACH STATEMENT EXECUTE FUNCTION {name}();"""
            else:
                # SQLite serializes writers; apply the net delta so unchanged buckets are never transiently removed.
                delta = f"""SELECT playlist_id, genre_id, SUM(n) AS n FROM (
                    SELECT playlist_id, genre_id, n FROM ({new_query}) additions
                    UNION ALL SELECT playlist_id, genre_id, -n FROM ({old_query}) removals
                    ) GROUP BY playlist_id, genre_id HAVING SUM(n) <> 0"""
                when = ""
                if event == "UPDATE":
                    when = " WHEN (" + " OR ".join(f"OLD.{col} IS NOT NEW.{col}" for col in relevant) + ")"
                if alias == "d":
                    markers = (["OLD"] if event != "INSERT" else []) + (["NEW"] if event != "DELETE" else [])
                    guard = "(" + " OR ".join(f"{marker}.key = 'grow'" for marker in markers) + ")"
                    when += (" AND " if when else " WHEN ") + guard
                sync = ""
                if alias in GENRE_SOURCES:
                    current = f"(SELECT m.genre_id FROM {VIEW} m WHERE m.track_id = {REL}.track_id)"
                    sync = f"""UPDATE {REL} SET genre_id = {current}
                        WHERE {scope(alias, rows, REL)} AND genre_id IS NOT {current};"""
                yield f"""CREATE TRIGGER {name} AFTER {event} ON {table}{when} BEGIN
                    SELECT CASE WHEN EXISTS (SELECT 1 FROM ({delta}) d
                        LEFT JOIN {CACHE} b ON b.playlist_id = d.playlist_id AND b.genre_id IS d.genre_id
                        WHERE d.n < 0 AND (b.id IS NULL OR b.tracks_count + d.n < 0))
                        THEN RAISE(ABORT, 'Genre membership count underflow') END;
                    UPDATE {CACHE} SET tracks_count = tracks_count + COALESCE((
                        SELECT d.n FROM ({delta}) d WHERE d.playlist_id = {CACHE}.playlist_id
                        AND d.genre_id IS {CACHE}.genre_id), 0);
                    INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count)
                        SELECT playlist_id, genre_id, n FROM ({delta}) d WHERE n > 0 AND NOT EXISTS (
                            SELECT 1 FROM {CACHE} b WHERE b.playlist_id = d.playlist_id AND b.genre_id IS d.genre_id);
                    DELETE FROM {CACHE} WHERE tracks_count = 0;
                    {sync}
                END"""
    if pg:
        yield f"""CREATE FUNCTION fill_rel_genre_from_membership() RETURNS trigger AS $$
            BEGIN
                SELECT genre_id INTO NEW.genre_id FROM {VIEW} WHERE track_id = NEW.track_id;
                RETURN NEW;
            END; $$ LANGUAGE plpgsql"""
        yield f"""CREATE TRIGGER fill_rel_genre_from_membership BEFORE INSERT ON {REL}
            FOR EACH ROW WHEN (NEW.genre_id IS NULL) EXECUTE FUNCTION fill_rel_genre_from_membership()"""
        population_all = population(tables, "1 = 1")
        # Existing TRUNCATE triggers on r, t, p and k already call this function; extend it to the new sources.
        yield f"""CREATE OR REPLACE FUNCTION rebuild_genre_membership_counts() RETURNS trigger AS $$
            BEGIN
                DELETE FROM {CACHE};
                INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count) {population_all};
                RETURN NULL;
            END; $$ LANGUAGE plpgsql"""
        for alias in ("a", "n", "d", "c"):
            yield f"""CREATE TRIGGER semantic_membership_truncate AFTER TRUNCATE ON {SOURCES[alias][0]}
                FOR EACH STATEMENT EXECUTE FUNCTION rebuild_genre_membership_counts()"""
    else:
        yield f"""CREATE TRIGGER fill_rel_genre_from_membership AFTER INSERT ON {REL} WHEN NEW.genre_id IS NULL
            BEGIN
                UPDATE {REL} SET genre_id = (SELECT genre_id FROM {VIEW} WHERE track_id = NEW.track_id)
                WHERE id = NEW.id;
            END"""


def drop_legacy(schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    for alias in ("r", "t", "p", "c"):
        table = BUCKETS.SOURCES[alias]
        for event in ("insert", "update", "delete"):
            name = f"genre_membership_{alias}_{event}"
            schema_editor.execute(f"DROP TRIGGER {name}" + (f" ON {table}" if pg else ""))
            if pg:
                schema_editor.execute(f"DROP FUNCTION {name}()")
    if pg:
        schema_editor.execute(f"DROP TRIGGER sync_rel_genre_from_track ON {BUCKETS.TRACK}")
        schema_editor.execute(f"DROP TRIGGER fill_rel_genre_from_track ON {REL}")
        schema_editor.execute("DROP FUNCTION sync_rel_genre_from_track()")
        schema_editor.execute("DROP FUNCTION fill_rel_genre_from_track()")
    else:
        schema_editor.execute("DROP TRIGGER sync_rel_genre_from_track")
        schema_editor.execute("DROP TRIGGER fill_rel_genre_from_track")


def has_dataset(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM {SOURCES['d'][0]} WHERE key = 'grow'")
        return cursor.fetchone() is not None


def forwards(apps, schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    if not pg and schema_editor.connection.vendor != "sqlite":
        raise NotImplementedError("Semantic playlist projection requires PostgreSQL or SQLite")
    using = schema_editor.connection.alias
    with transaction.atomic(using=using):
        if pg:
            tables = sorted({table for table, _, _ in SOURCES.values()} | {CACHE})
            # Reject a busy migration rather than wait with relation locks while a writer holds the source gate.
            schema_editor.execute(f"LOCK TABLE {', '.join(tables)} IN ACCESS EXCLUSIVE MODE NOWAIT")
            schema_editor.execute(f"""DO $$ BEGIN
                IF NOT pg_try_advisory_xact_lock({LOCK_KEY}) THEN
                    RAISE EXCEPTION 'Playlist source gate is busy; retry migration';
                END IF;
            END $$""")
        drop_legacy(schema_editor)
        for statement in statements(schema_editor):
            schema_editor.execute(statement)
        # Without a dataset the effective genre is the legacy column: rows and buckets are already exact.
        dataset = has_dataset(schema_editor)
        if dataset:
            schema_editor.execute(f"DELETE FROM {CACHE}")
            schema_editor.execute(
                f"INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count) "
                + population(
                    {alias: table for alias, (table, _, _) in SOURCES.items()},
                    "1 = 1",
                )
            )
    if dataset:
        differs = "IS DISTINCT FROM" if pg else "IS NOT"
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f"SELECT MIN(id), MAX(id) FROM {REL}")
            low, high = cursor.fetchone()
            if low is None:
                return
            for start in range(low, high + 1, BATCH):
                with transaction.atomic(using=using):
                    if pg:
                        cursor.execute(f"SELECT pg_advisory_xact_lock({LOCK_KEY})")
                    cursor.execute(
                        f"""UPDATE {REL} SET genre_id = m.genre_id FROM {VIEW} m
                        WHERE m.track_id = {REL}.track_id AND {REL}.id >= %s AND {REL}.id < %s
                        AND {REL}.genre_id {differs} m.genre_id""",
                        [start, start + BATCH],
                    )


def backwards(apps, schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    with transaction.atomic(using=schema_editor.connection.alias):
        for alias, (table, _, _) in SOURCES.items():
            for event in ("insert", "update", "delete"):
                name = f"semantic_membership_{alias}_{event}"
                schema_editor.execute(f"DROP TRIGGER {name}" + (f" ON {table}" if pg else ""))
                if pg:
                    schema_editor.execute(f"DROP FUNCTION {name}()")
        if pg:
            for alias in ("a", "n", "d", "c"):
                schema_editor.execute(f"DROP TRIGGER semantic_membership_truncate ON {SOURCES[alias][0]}")
            schema_editor.execute(f"DROP TRIGGER fill_rel_genre_from_membership ON {REL}")
            schema_editor.execute("DROP FUNCTION fill_rel_genre_from_membership()")
        else:
            schema_editor.execute("DROP TRIGGER fill_rel_genre_from_membership")
        gate = (
            "CREATE TRIGGER lock_genre_membership_sources BEFORE INSERT OR UPDATE OF track_id OR DELETE OR TRUNCATE "
            "ON grow_song FOR EACH STATEMENT EXECUTE FUNCTION lock_genre_membership_sources()"
        )
        if pg:
            # The catalogue gate (0115) shares the function that 0108 drops and recreates.
            schema_editor.execute("DROP TRIGGER lock_genre_membership_sources ON grow_song")
        BUCKETS.drop(apps, schema_editor)
        BUCKETS.create(apps, schema_editor)
        if pg:
            schema_editor.execute(gate)
    # Reinstalls the legacy rel triggers and reconciles `genre_id` with `Track.genre_id`.
    REL_SYNC.forwards(apps, schema_editor)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("grow", "0141_semantic_catalogue_projection")]
    operations = [migrations.RunPython(forwards, backwards)]
