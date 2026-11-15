"""Resolve direct membership without turning Track.genre into a second semantic authority."""

import django.db.models.deletion
from django.db import migrations, models

TRACK = "the_music_tree_genre_kit_track"
ATTRIBUTION = "the_music_tree_genre_kit_genregraphattribution"
NODE = "the_music_tree_genre_kit_genregraphnode"
DATASET = "the_music_tree_genre_kit_genregraphdataset"
VIEW = "grow_song_membership"

VIEW_SQL = f"""CREATE VIEW {VIEW} AS
    SELECT t.uuid AS track_id, t.genre_id FROM {TRACK} t
    WHERE NOT EXISTS (SELECT 1 FROM {DATASET} WHERE key = 'grow')
    UNION ALL
    SELECT t.uuid AS track_id, c.uuid AS genre_id FROM {TRACK} t
    LEFT JOIN (
        SELECT a.track_id, a.node_id FROM {ATTRIBUTION} a
        JOIN {NODE} n ON n.id = a.node_id WHERE n.dataset_id = 'grow' AND n.is_active
    ) a ON a.track_id = t.uuid
    LEFT JOIN grow_criteria c ON c.graph_node_id = a.node_id
    WHERE EXISTS (SELECT 1 FROM {DATASET} WHERE key = 'grow')
"""


def create_boundary(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor not in {"sqlite", "postgresql"}:
        raise RuntimeError("Song membership requires PostgreSQL or SQLite")
    if vendor == "postgresql":
        # Reject busy migrations rather than waiting with a relation lock while a writer holds the source gate.
        schema_editor.execute(f"LOCK TABLE {ATTRIBUTION} IN ACCESS EXCLUSIVE MODE NOWAIT")
        schema_editor.execute("""DO $$ BEGIN
            IF NOT pg_try_advisory_xact_lock(716731928417) THEN
                RAISE EXCEPTION 'Song membership source gate is busy; retry the migration';
            END IF;
        END $$""")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"""SELECT a.track_id FROM {ATTRIBUTION} a JOIN {NODE} n ON n.id = a.node_id
            WHERE n.dataset_id = 'grow' GROUP BY a.track_id HAVING COUNT(*) > 1 LIMIT 1""")
        if cursor.fetchone():
            raise RuntimeError("Grow songs must have at most one directly assigned genre before cutover")
    schema_editor.execute(VIEW_SQL)
    different = f"""EXISTS (SELECT 1 FROM {ATTRIBUTION} a JOIN {NODE} n ON n.id = a.node_id
        WHERE n.dataset_id = 'grow' AND a.track_id = NEW.track_id AND a.id <> NEW.id)"""
    is_grow = f"EXISTS (SELECT 1 FROM {NODE} WHERE id = NEW.node_id AND dataset_id = 'grow')"
    if vendor == "postgresql":
        schema_editor.execute("""CREATE FUNCTION grow_assignment_source_gate() RETURNS trigger AS $$
        BEGIN
            IF current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Grow attribution writes require READ COMMITTED isolation';
            END IF;
            PERFORM pg_advisory_xact_lock(716731928417);
            RETURN NULL;
        END; $$ LANGUAGE plpgsql""")
        schema_editor.execute(f"""CREATE TRIGGER grow_assignment_source_gate BEFORE INSERT OR UPDATE OR DELETE
            ON {ATTRIBUTION} FOR EACH STATEMENT EXECUTE FUNCTION grow_assignment_source_gate()""")
        schema_editor.execute(f"""CREATE FUNCTION grow_single_assignment_guard() RETURNS trigger AS $$
        BEGIN
            IF {is_grow} AND {different} THEN
                RAISE EXCEPTION 'A song can have at most one directly assigned genre' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        schema_editor.execute(f"""CREATE TRIGGER grow_single_assignment_guard BEFORE INSERT OR UPDATE
            ON {ATTRIBUTION} FOR EACH ROW EXECUTE FUNCTION grow_single_assignment_guard()""")
    else:
        for event in ("INSERT", "UPDATE"):
            schema_editor.execute(f"""CREATE TRIGGER grow_single_assignment_{event.lower()}
                BEFORE {event} ON {ATTRIBUTION} WHEN {is_grow} AND {different}
                BEGIN SELECT RAISE(ABORT, 'A song can have at most one directly assigned genre'); END""")


def drop_boundary(apps, schema_editor):
    schema_editor.execute(f"DROP VIEW {VIEW}")
    if schema_editor.connection.vendor == "postgresql":
        for name in ("grow_single_assignment_guard", "grow_assignment_source_gate"):
            schema_editor.execute(f"DROP TRIGGER {name} ON {ATTRIBUTION}")
            schema_editor.execute(f"DROP FUNCTION {name}()")
    else:
        for event in ("insert", "update"):
            schema_editor.execute(f"DROP TRIGGER grow_single_assignment_{event}")


class Migration(migrations.Migration):
    dependencies = [("grow", "0139_overview_status_overrides_list")]
    operations = [
        migrations.CreateModel(
            name="SongMembership",
            fields=[
                (
                    "track",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        primary_key=True,
                        serialize=False,
                        related_name="song_membership",
                        to="the_music_tree_genre_kit.track",
                    ),
                ),
                (
                    "genre",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="grow.genre",
                    ),
                ),
            ],
            options={"managed": False, "db_table": VIEW},
        ),
        migrations.RunPython(create_boundary, drop_boundary),
    ]
