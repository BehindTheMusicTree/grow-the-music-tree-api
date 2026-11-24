"""Derive playlist membership buckets and `TrackPlaylistRel.genre_id` from `grow_song.genre_id`.

Without a `grow` dataset the song genre is `Track.genre_id`, so existing rows and counts are unchanged.
"""

from importlib import import_module

from django.db import migrations, transaction

BUCKETS = import_module("grow.migrations.0108_maintain_genre_membership_counts")
REL_SYNC = import_module("grow.migrations.0118_maintain_track_playlist_rel_genre")
CACHE, REL, TRACK = BUCKETS.CACHE, BUCKETS.REL, BUCKETS.TRACK
SONG = "grow_song"
BATCH = REL_SYNC.BATCH
LOCK_KEY = 716731928417
SOURCES = {**BUCKETS.SOURCES, "s": SONG}
KEYS = {"r": "id", "t": "uuid", "p": "uuid", "c": "playlist_id", "s": "track_id"}
COLUMNS = {
    "r": ("id", "playlist_id", "track_id", "user_id"),
    "t": ("uuid", "user_id"),
    "p": ("uuid", "user_id"),
    "c": ("playlist_id", "type_id"),
    "s": ("track_id", "genre_id"),
}


def source_query(alias=None, replacement=None, predicate="TRUE"):
    tables = {key: replacement if key == alias else table for key, table in SOURCES.items()}
    return f"""
        SELECT r.playlist_id, s.genre_id, COUNT(*) AS n
        FROM {tables["r"]} r
        JOIN {tables["t"]} t ON t.uuid = r.track_id
        JOIN {tables["s"]} s ON s.track_id = t.uuid
        JOIN {tables["p"]} p ON p.uuid = r.playlist_id
        JOIN {tables["c"]} c ON c.playlist_id = p.uuid
        WHERE r.user_id IS NULL AND t.user_id IS NULL AND p.user_id IS NULL
          AND c.type_id = 0 AND ({predicate})
        GROUP BY r.playlist_id, s.genre_id
    """


def postgres_statements():
    for alias, table in SOURCES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            parts, references = [], []
            if event != "DELETE":
                parts.append(f"SELECT playlist_id, genre_id, n FROM ({source_query(alias, 'new_rows')}) additions")
                references.append("NEW TABLE AS new_rows")
            if event != "INSERT":
                parts.append(f"SELECT playlist_id, genre_id, -n AS n FROM ({source_query(alias, 'old_rows')}) removals")
                references.append("OLD TABLE AS old_rows")
            name = f"genre_membership_{alias}_{event.lower()}"
            unchanged = ""
            if event == "UPDATE":
                key = KEYS[alias]
                relevant = {**COLUMNS, "r": COLUMNS["r"][1:]}[alias]
                differs = " OR ".join(f"o.{col} IS DISTINCT FROM n.{col}" for col in relevant)
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
    yield f"""
        CREATE OR REPLACE FUNCTION rebuild_genre_membership_counts() RETURNS trigger AS $$
        BEGIN
            DELETE FROM {CACHE};
            INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count) {source_query()};
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """
    yield f"""CREATE TRIGGER rebuild_genre_membership_counts AFTER TRUNCATE ON {SONG}
        FOR EACH STATEMENT EXECUTE FUNCTION rebuild_genre_membership_counts()"""
    yield f"""CREATE OR REPLACE FUNCTION fill_rel_genre_from_track() RETURNS trigger AS $$
        BEGIN
            SELECT genre_id INTO NEW.genre_id FROM {SONG} WHERE track_id = NEW.track_id;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql"""
    yield f"""CREATE FUNCTION sync_rel_genre_from_track() RETURNS trigger AS $$
        BEGIN
            UPDATE {REL} r SET genre_id = n.genre_id
            FROM new_rows n JOIN old_rows o ON o.track_id = n.track_id
            WHERE r.track_id = n.track_id AND o.genre_id IS DISTINCT FROM n.genre_id
              AND r.genre_id IS DISTINCT FROM n.genre_id;
            RETURN NULL;
        END; $$ LANGUAGE plpgsql"""
    yield f"""CREATE TRIGGER sync_rel_genre_from_track AFTER UPDATE ON {SONG}
        REFERENCING NEW TABLE AS new_rows OLD TABLE AS old_rows
        FOR EACH STATEMENT EXECUTE FUNCTION sync_rel_genre_from_track()"""


def sqlite_statements():
    for alias, table in SOURCES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            statements = []
            for row, sign in (("OLD", -1), ("NEW", 1)):
                if (event == "INSERT" and row == "OLD") or (event == "DELETE" and row == "NEW"):
                    continue
                replacement = "(SELECT " + ", ".join(f"{row}.{col} AS {col}" for col in COLUMNS[alias]) + ")"
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
            relevant = {**COLUMNS, "r": COLUMNS["r"][1:]}[alias]
            when = (
                " WHEN " + " OR ".join(f"OLD.{col} IS NOT NEW.{col}" for col in relevant) if event == "UPDATE" else ""
            )
            yield (
                f"CREATE TRIGGER genre_membership_{alias}_{event.lower()} AFTER {event} ON {table}{when} "
                f"BEGIN {' '.join(statements)} END;"
            )
    yield f"""CREATE TRIGGER sync_rel_genre_from_track AFTER UPDATE OF genre_id ON {SONG}
        WHEN OLD.genre_id IS NOT NEW.genre_id
        BEGIN UPDATE {REL} SET genre_id = NEW.genre_id WHERE track_id = NEW.track_id; END"""
    yield f"""CREATE TRIGGER fill_rel_genre_from_track AFTER INSERT ON {REL} WHEN NEW.genre_id IS NULL
        BEGIN
            UPDATE {REL} SET genre_id = (SELECT genre_id FROM {SONG} WHERE track_id = NEW.track_id)
            WHERE id = NEW.id;
        END"""


def drop_legacy(schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    for alias in ("r", "t", "p", "c"):
        table = SOURCES[alias]
        for event in ("insert", "update", "delete"):
            name = f"genre_membership_{alias}_{event}"
            schema_editor.execute(f"DROP TRIGGER {name}" + (f" ON {table}" if pg else ""))
            if pg:
                schema_editor.execute(f"DROP FUNCTION {name}()")
    if pg:
        schema_editor.execute(f"DROP TRIGGER sync_rel_genre_from_track ON {TRACK}")
        schema_editor.execute("DROP FUNCTION sync_rel_genre_from_track()")
    else:
        schema_editor.execute("DROP TRIGGER sync_rel_genre_from_track")
        schema_editor.execute("DROP TRIGGER fill_rel_genre_from_track")


def has_dataset(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM the_music_tree_genre_kit_genregraphdataset WHERE key = 'grow'")
        return cursor.fetchone() is not None


def forwards(apps, schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    if not pg and schema_editor.connection.vendor != "sqlite":
        raise NotImplementedError("Playlist projection requires PostgreSQL or SQLite")
    using = schema_editor.connection.alias
    with transaction.atomic(using=using):
        drop_legacy(schema_editor)
        for statement in postgres_statements() if pg else sqlite_statements():
            schema_editor.execute(statement)
        # Without a dataset the song genre is the legacy column: rows and buckets are already exact.
        dataset = has_dataset(schema_editor)
        if dataset:
            schema_editor.execute(f"DELETE FROM {CACHE}")
            schema_editor.execute(f"INSERT INTO {CACHE} (playlist_id, genre_id, tracks_count) {source_query()}")
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
                        f"""UPDATE {REL} SET genre_id = s.genre_id FROM {SONG} s
                        WHERE s.track_id = {REL}.track_id AND {REL}.id >= %s AND {REL}.id < %s
                        AND {REL}.genre_id {differs} s.genre_id""",
                        [start, start + BATCH],
                    )


def backwards(apps, schema_editor):
    pg = schema_editor.connection.vendor == "postgresql"
    with transaction.atomic(using=schema_editor.connection.alias):
        for event in ("insert", "update", "delete"):
            name = f"genre_membership_s_{event}"
            schema_editor.execute(f"DROP TRIGGER {name}" + (f" ON {SONG}" if pg else ""))
            if pg:
                schema_editor.execute(f"DROP FUNCTION {name}()")
        if pg:
            schema_editor.execute(f"DROP TRIGGER rebuild_genre_membership_counts ON {SONG}")
            schema_editor.execute(f"DROP TRIGGER sync_rel_genre_from_track ON {SONG}")
            schema_editor.execute("DROP FUNCTION sync_rel_genre_from_track()")
            # The catalogue gate (0141) shares the function that 0108 drops and recreates.
            schema_editor.execute(f"DROP TRIGGER lock_genre_membership_sources ON {SONG}")
        else:
            schema_editor.execute("DROP TRIGGER sync_rel_genre_from_track")
        BUCKETS.drop(apps, schema_editor)
        BUCKETS.create(apps, schema_editor)
        if pg:
            schema_editor.execute(
                "CREATE TRIGGER lock_genre_membership_sources BEFORE INSERT OR UPDATE OF track_id, genre_id OR DELETE "
                f"OR TRUNCATE ON {SONG} FOR EACH STATEMENT EXECUTE FUNCTION lock_genre_membership_sources()"
            )
    # Reinstalls the legacy rel triggers and reconciles `genre_id` with `Track.genre_id`.
    REL_SYNC.forwards(apps, schema_editor)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("grow", "0141_semantic_catalogue_projection")]
    operations = [migrations.RunPython(forwards, backwards)]
