"""Materialise a song's effective genre on `grow_song.genre_id`, maintained by triggers.

Without a `grow` dataset the effective genre is `Track.genre_id`; once the dataset exists it is the criteria bound to
the song's single active attribution node. Readers join `grow_song`, never a view, so the read path stays a column.
"""

import django.db.models.deletion
from django.db import migrations, models, transaction

TRACK = "the_music_tree_genre_kit_track"
ATTRIBUTION = "the_music_tree_genre_kit_genregraphattribution"
NODE = "the_music_tree_genre_kit_genregraphnode"
DATASET = "the_music_tree_genre_kit_genregraphdataset"
SONG = "grow_song"
CRITERIA = "grow_criteria"
LOCK_KEY = 716731928417
BATCH = 50_000
SKIP = "current_setting('grow.membership_maintenance', true) = 'on'"


def effective(track):
    """The song's genre as the database derives it, for a track-id expression."""
    return f"""CASE WHEN EXISTS (SELECT 1 FROM {DATASET} WHERE key = 'grow')
        THEN (SELECT c.uuid FROM {ATTRIBUTION} a
            JOIN {NODE} n ON n.id = a.node_id AND n.dataset_id = 'grow' AND n.is_active
            JOIN {CRITERIA} c ON c.graph_node_id = a.node_id WHERE a.track_id = {track} LIMIT 1)
        ELSE (SELECT genre_id FROM {TRACK} WHERE uuid = {track}) END"""


def single_assignment_condition(row):
    different = f"""EXISTS (SELECT 1 FROM {ATTRIBUTION} a JOIN {NODE} n ON n.id = a.node_id
        WHERE n.dataset_id = 'grow' AND a.track_id = {row}.track_id AND a.id <> {row}.id)"""
    is_grow = f"EXISTS (SELECT 1 FROM {NODE} WHERE id = {row}.node_id AND dataset_id = 'grow')"
    return f"{is_grow} AND {different}"


def postgres_statements():
    yield f"""CREATE FUNCTION grow_effective_genre(p_track uuid) RETURNS uuid AS $$
        SELECT {effective("p_track")} $$ LANGUAGE sql STABLE"""
    yield f"""CREATE FUNCTION grow_song_genre_gate() RETURNS trigger AS $$
        BEGIN
            IF current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Song genre writes require READ COMMITTED isolation';
            END IF;
            PERFORM pg_advisory_xact_lock({LOCK_KEY});
            RETURN NULL;
        END; $$ LANGUAGE plpgsql"""
    for table in (ATTRIBUTION, NODE, DATASET):
        yield f"""CREATE TRIGGER grow_song_genre_gate BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
            ON {table} FOR EACH STATEMENT EXECUTE FUNCTION grow_song_genre_gate()"""
    yield """CREATE FUNCTION grow_song_genre_fill() RETURNS trigger AS $$
        BEGIN
            IF NOT (""" + SKIP + """) THEN NEW.genre_id := grow_effective_genre(NEW.track_id); END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql"""
    yield f"""CREATE TRIGGER grow_song_genre_fill BEFORE INSERT ON {SONG}
        FOR EACH ROW EXECUTE FUNCTION grow_song_genre_fill()"""
    # Triggers fire at depth 1; their own UPDATE reaches this guard at depth 2. A direct write may only clear the
    # column (a genre delete's SET NULL) or restate the derived value.
    yield f"""CREATE FUNCTION grow_song_genre_guard() RETURNS trigger AS $$
        BEGIN
            IF pg_trigger_depth() <= 1 AND NOT ({SKIP}) AND NEW.genre_id IS NOT NULL
               AND NEW.genre_id IS DISTINCT FROM grow_effective_genre(NEW.track_id) THEN
                RAISE EXCEPTION 'grow_song.genre_id is derived from the grow dataset and cannot be written directly'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql"""
    yield f"""CREATE TRIGGER grow_song_genre_guard BEFORE UPDATE OF genre_id ON {SONG}
        FOR EACH ROW WHEN (OLD.genre_id IS DISTINCT FROM NEW.genre_id) EXECUTE FUNCTION grow_song_genre_guard()"""

    def refresh(scope):
        return f"""UPDATE {SONG} s SET genre_id = grow_effective_genre(s.track_id)
            WHERE s.track_id IN ({scope}) AND s.genre_id IS DISTINCT FROM grow_effective_genre(s.track_id);"""

    def node_tracks(node_ids):
        return f"SELECT track_id FROM {ATTRIBUTION} WHERE node_id IN ({node_ids})"

    def changed(changed_columns, key):
        return f"""SELECT n.{key} FROM new_rows n JOIN old_rows o ON o.{key} = n.{key}
            WHERE {" OR ".join(f"o.{c} IS DISTINCT FROM n.{c}" for c in changed_columns)}"""

    new_ids, old_ids = "SELECT track_id FROM new_rows", "SELECT track_id FROM old_rows"
    scopes = {
        (TRACK, "UPDATE"): changed(("genre_id",), "uuid"),
        (ATTRIBUTION, "INSERT"): new_ids,
        (ATTRIBUTION, "UPDATE"): f"{new_ids} UNION {old_ids}",
        (ATTRIBUTION, "DELETE"): old_ids,
        (NODE, "UPDATE"): node_tracks(changed(("is_active", "dataset_id"), "id")),
        (CRITERIA, "INSERT"): node_tracks("SELECT graph_node_id FROM new_rows WHERE graph_node_id IS NOT NULL"),
        (CRITERIA, "UPDATE"): node_tracks(
            f"""SELECT n.graph_node_id FROM new_rows n JOIN old_rows o ON o.uuid = n.uuid
            WHERE o.graph_node_id IS DISTINCT FROM n.graph_node_id AND n.graph_node_id IS NOT NULL
            UNION SELECT o.graph_node_id FROM new_rows n JOIN old_rows o ON o.uuid = n.uuid
            WHERE o.graph_node_id IS DISTINCT FROM n.graph_node_id AND o.graph_node_id IS NOT NULL"""
        ),
        (CRITERIA, "DELETE"): node_tracks("SELECT graph_node_id FROM old_rows WHERE graph_node_id IS NOT NULL"),
    }
    for (table, event), scope in scopes.items():
        name = f"grow_song_genre_{table.removeprefix('the_music_tree_genre_kit_')}_{event.lower()}"
        refs = {"INSERT": "NEW TABLE AS new_rows", "DELETE": "OLD TABLE AS old_rows"}.get(
            event, "OLD TABLE AS old_rows NEW TABLE AS new_rows"
        )
        yield f"""CREATE FUNCTION {name}() RETURNS trigger AS $$
            BEGIN
                IF {SKIP} THEN RETURN NULL; END IF;
                {refresh(scope)}
                RETURN NULL;
            END; $$ LANGUAGE plpgsql;
            CREATE TRIGGER {name} AFTER {event} ON {table}
            REFERENCING {refs} FOR EACH STATEMENT EXECUTE FUNCTION {name}()"""
    # Creating or removing the dataset switches every song between the legacy column and the attributions.
    yield f"""CREATE FUNCTION grow_song_genre_dataset() RETURNS trigger AS $$
        BEGIN
            IF {SKIP} THEN RETURN NULL; END IF;
            IF EXISTS (SELECT 1 FROM changes WHERE key = 'grow') THEN
                UPDATE {SONG} s SET genre_id = grow_effective_genre(s.track_id)
                WHERE s.genre_id IS DISTINCT FROM grow_effective_genre(s.track_id);
            END IF;
            RETURN NULL;
        END; $$ LANGUAGE plpgsql"""
    for event, ref in (("INSERT", "NEW"), ("DELETE", "OLD")):
        yield f"""CREATE TRIGGER grow_song_genre_dataset_{event.lower()} AFTER {event} ON {DATASET}
            REFERENCING {ref} TABLE AS changes FOR EACH STATEMENT EXECUTE FUNCTION grow_song_genre_dataset()"""
    yield f"""CREATE FUNCTION grow_single_assignment_guard() RETURNS trigger AS $$
        BEGIN
            IF {single_assignment_condition("NEW")} THEN
                RAISE EXCEPTION 'A song can have at most one directly assigned genre' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql"""
    yield f"""CREATE TRIGGER grow_single_assignment_guard BEFORE INSERT OR UPDATE
        ON {ATTRIBUTION} FOR EACH ROW EXECUTE FUNCTION grow_single_assignment_guard()"""


def sqlite_statements():
    def refresh(scope):
        return f"""UPDATE {SONG} SET genre_id = {effective(f"{SONG}.track_id")}
            WHERE {scope} AND genre_id IS NOT {effective(f"{SONG}.track_id")};"""

    def node_tracks(node_ids):
        return f"SELECT track_id FROM {ATTRIBUTION} WHERE node_id IN ({node_ids})"

    def trigger(name, event, table, scope, when=""):
        return f"CREATE TRIGGER {name} AFTER {event} ON {table}{when} BEGIN {refresh(scope)} END"

    yield trigger("grow_song_genre_fill", "INSERT", SONG, f"{SONG}.track_id = NEW.track_id")
    yield trigger(
        "grow_song_genre_track_update",
        "UPDATE OF genre_id",
        TRACK,
        f"{SONG}.track_id = NEW.uuid",
        " WHEN OLD.genre_id IS NOT NEW.genre_id",
    )
    yield trigger("grow_song_genre_attribution_insert", "INSERT", ATTRIBUTION, f"{SONG}.track_id = NEW.track_id")
    yield trigger(
        "grow_song_genre_attribution_update",
        "UPDATE",
        ATTRIBUTION,
        f"{SONG}.track_id IN (NEW.track_id, OLD.track_id)",
    )
    yield trigger("grow_song_genre_attribution_delete", "DELETE", ATTRIBUTION, f"{SONG}.track_id = OLD.track_id")
    yield trigger(
        "grow_song_genre_node_update",
        "UPDATE OF is_active, dataset_id",
        NODE,
        f"{SONG}.track_id IN ({node_tracks('NEW.id')})",
    )
    yield trigger(
        "grow_song_genre_criteria_insert",
        "INSERT",
        CRITERIA,
        f"{SONG}.track_id IN ({node_tracks('NEW.graph_node_id')})",
    )
    yield trigger(
        "grow_song_genre_criteria_update",
        "UPDATE OF graph_node_id",
        CRITERIA,
        f"{SONG}.track_id IN ({node_tracks('NEW.graph_node_id, OLD.graph_node_id')})",
        " WHEN OLD.graph_node_id IS NOT NEW.graph_node_id",
    )
    yield trigger(
        "grow_song_genre_criteria_delete",
        "DELETE",
        CRITERIA,
        f"{SONG}.track_id IN ({node_tracks('OLD.graph_node_id')})",
    )
    yield trigger("grow_song_genre_dataset_insert", "INSERT", DATASET, "1 = 1", " WHEN NEW.key = 'grow'")
    yield trigger("grow_song_genre_dataset_delete", "DELETE", DATASET, "1 = 1", " WHEN OLD.key = 'grow'")
    for event in ("INSERT", "UPDATE"):
        yield f"""CREATE TRIGGER grow_single_assignment_{event.lower()} BEFORE {event} ON {ATTRIBUTION}
            WHEN {single_assignment_condition("NEW")}
            BEGIN SELECT RAISE(ABORT, 'A song can have at most one directly assigned genre'); END"""


def backfill(schema_editor):
    """Fill the column in short transactions; the triggers already cover rows written meanwhile."""
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {SONG} SET genre_id = {effective(f'{SONG}.track_id')}")
        return
    with connection.cursor() as cursor:
        last = None
        while True:
            with transaction.atomic(using=connection.alias):
                cursor.execute("SELECT set_config('grow.membership_maintenance', 'on', true)")
                cursor.execute(f"SELECT pg_advisory_xact_lock({LOCK_KEY})")
                cursor.execute(
                    f"SELECT track_id FROM {SONG} WHERE %s::uuid IS NULL OR track_id > %s ORDER BY track_id "
                    "OFFSET %s LIMIT 1",
                    [last, last, BATCH - 1],
                )
                row = cursor.fetchone()
                upper = row[0] if row else None
                cursor.execute(
                    f"""UPDATE {SONG} s SET genre_id = grow_effective_genre(s.track_id)
                    WHERE (%s::uuid IS NULL OR s.track_id > %s) AND (%s::uuid IS NULL OR s.track_id <= %s)
                    AND s.genre_id IS DISTINCT FROM grow_effective_genre(s.track_id)""",
                    [last, last, upper, upper],
                )
            if upper is None:
                return
            last = upper


def add_column(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        # A table remake drops the triggers of the tables referencing grow_song; a plain column keeps them.
        schema_editor.execute(f"ALTER TABLE {SONG} ADD COLUMN genre_id char(32) NULL")
        schema_editor.execute(f"CREATE INDEX {SONG}_genre_id_idx ON {SONG} (genre_id)")
        return
    schema_editor.execute(
        f"ALTER TABLE {SONG} ADD COLUMN genre_id uuid NULL REFERENCES grow_genre (criteria_ptr_id) "
        "ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED"
    )
    schema_editor.execute(f"CREATE INDEX {SONG}_genre_id_idx ON {SONG} (genre_id)")


def drop_column(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.execute(f"DROP INDEX {SONG}_genre_id_idx")
    schema_editor.execute(f"ALTER TABLE {SONG} DROP COLUMN genre_id")


def create_boundary(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor not in {"sqlite", "postgresql"}:
        raise RuntimeError("Song membership requires PostgreSQL or SQLite")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"""SELECT a.track_id FROM {ATTRIBUTION} a JOIN {NODE} n ON n.id = a.node_id
            WHERE n.dataset_id = 'grow' GROUP BY a.track_id HAVING COUNT(*) > 1 LIMIT 1""")
        if cursor.fetchone():
            raise RuntimeError("Grow songs must have at most one directly assigned genre before cutover")
    statements = postgres_statements() if vendor == "postgresql" else sqlite_statements()
    with transaction.atomic(using=schema_editor.connection.alias):
        for statement in statements:
            schema_editor.execute(statement)
    backfill(schema_editor)


def drop_boundary(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        sources = {
            ATTRIBUTION: ("insert", "update", "delete"),
            NODE: ("update",),
            CRITERIA: ("insert", "update", "delete"),
            TRACK: ("update",),
        }
        for table, events in sources.items():
            for event in events:
                name = f"grow_song_genre_{table.removeprefix('the_music_tree_genre_kit_')}_{event}"
                schema_editor.execute(f"DROP TRIGGER {name} ON {table}")
                schema_editor.execute(f"DROP FUNCTION {name}()")
        for event in ("insert", "delete"):
            schema_editor.execute(f"DROP TRIGGER grow_song_genre_dataset_{event} ON {DATASET}")
        for table in (ATTRIBUTION, NODE, DATASET):
            schema_editor.execute(f"DROP TRIGGER grow_song_genre_gate ON {table}")
        schema_editor.execute(f"DROP TRIGGER grow_single_assignment_guard ON {ATTRIBUTION}")
        schema_editor.execute(f"DROP TRIGGER grow_song_genre_fill ON {SONG}")
        schema_editor.execute(f"DROP TRIGGER grow_song_genre_guard ON {SONG}")
        for function in (
            "grow_song_genre_dataset()",
            "grow_song_genre_gate()",
            "grow_single_assignment_guard()",
            "grow_song_genre_fill()",
            "grow_song_genre_guard()",
            "grow_effective_genre(uuid)",
        ):
            schema_editor.execute(f"DROP FUNCTION {function}")
    else:
        for name in (
            "grow_song_genre_fill",
            "grow_song_genre_track_update",
            "grow_song_genre_attribution_insert",
            "grow_song_genre_attribution_update",
            "grow_song_genre_attribution_delete",
            "grow_song_genre_node_update",
            "grow_song_genre_criteria_insert",
            "grow_song_genre_criteria_update",
            "grow_song_genre_criteria_delete",
            "grow_song_genre_dataset_insert",
            "grow_song_genre_dataset_delete",
            "grow_single_assignment_insert",
            "grow_single_assignment_update",
        ):
            schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("grow", "0139_overview_status_overrides_list")]
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="song",
                    name="membership_genre",
                    field=models.ForeignKey(
                        db_column="genre_id",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="grow.genre",
                    ),
                )
            ],
            database_operations=[migrations.RunPython(add_column, drop_column)],
        ),
        migrations.RunPython(create_boundary, drop_boundary),
    ]
