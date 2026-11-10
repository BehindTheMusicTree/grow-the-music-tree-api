from django.db import migrations

REL = "the_music_tree_genre_kit_track_playlist_rel"
TRACK = "the_music_tree_genre_kit_track"
BATCH = 50_000

# `TrackPlaylistRel.genre` is a denormalised copy of `track.genre`. Two invariants keep it exact:
# a track's genre change is pushed to its memberships, and a membership inserted without a genre
# copies the track's. Bulk writers (bulk_import/merge.py) set it explicitly and skip the lookup.

POSTGRES_UP = (
    f"""
    CREATE OR REPLACE FUNCTION sync_rel_genre_from_track() RETURNS trigger AS $$
    BEGIN
        UPDATE {REL} r SET genre_id = n.genre_id
        FROM new_rows n JOIN old_rows o ON o.uuid = n.uuid
        WHERE r.track_id = n.uuid AND o.genre_id IS DISTINCT FROM n.genre_id AND r.genre_id IS DISTINCT FROM n.genre_id;
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    f"DROP TRIGGER IF EXISTS sync_rel_genre_from_track ON {TRACK}",
    f"""
    CREATE TRIGGER sync_rel_genre_from_track AFTER UPDATE ON {TRACK}
    REFERENCING NEW TABLE AS new_rows OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION sync_rel_genre_from_track()
    """,
    """
    CREATE OR REPLACE FUNCTION fill_rel_genre_from_track() RETURNS trigger AS $$
    BEGIN
        SELECT genre_id INTO NEW.genre_id FROM the_music_tree_genre_kit_track WHERE uuid = NEW.track_id;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    f"DROP TRIGGER IF EXISTS fill_rel_genre_from_track ON {REL}",
    f"""
    CREATE TRIGGER fill_rel_genre_from_track BEFORE INSERT ON {REL}
    FOR EACH ROW WHEN (NEW.genre_id IS NULL) EXECUTE FUNCTION fill_rel_genre_from_track()
    """,
)

SQLITE_UP = (
    "DROP TRIGGER IF EXISTS sync_rel_genre_from_track",
    f"""
    CREATE TRIGGER sync_rel_genre_from_track AFTER UPDATE OF genre_id ON {TRACK}
    WHEN OLD.genre_id IS NOT NEW.genre_id
    BEGIN UPDATE {REL} SET genre_id = NEW.genre_id WHERE track_id = NEW.uuid; END
    """,
    "DROP TRIGGER IF EXISTS fill_rel_genre_from_track",
    f"""
    CREATE TRIGGER fill_rel_genre_from_track AFTER INSERT ON {REL} WHEN NEW.genre_id IS NULL
    BEGIN
        UPDATE {REL} SET genre_id = (SELECT genre_id FROM {TRACK} WHERE uuid = NEW.track_id) WHERE id = NEW.id;
    END
    """,
)


def forwards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor not in ("postgresql", "sqlite"):
        raise NotImplementedError(f"No rel genre triggers for {vendor}")
    # Triggers first, so a track or membership written during the backfill is covered too.
    for statement in POSTGRES_UP if vendor == "postgresql" else SQLITE_UP:
        schema_editor.execute(statement)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT MIN(id), MAX(id) FROM {REL}")
        low, high = cursor.fetchone()
        if low is None:
            return
        # One short statement per id range (the migration is non-atomic): the membership write gate is held only
        # for a batch, never for the whole backfill. NULL-genre rows already match their genreless track.
        for start in range(low, high + 1, BATCH):
            cursor.execute(
                f"""UPDATE {REL} SET genre_id = t.genre_id FROM {TRACK} t
                WHERE t.uuid = {REL}.track_id AND {REL}.id >= %s AND {REL}.id < %s
                AND t.genre_id IS NOT NULL AND {REL}.genre_id IS NULL""",
                [start, start + BATCH],
            )


def backwards(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(f"DROP TRIGGER IF EXISTS sync_rel_genre_from_track ON {TRACK}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS fill_rel_genre_from_track ON {REL}")
        schema_editor.execute("DROP FUNCTION IF EXISTS sync_rel_genre_from_track()")
        schema_editor.execute("DROP FUNCTION IF EXISTS fill_rel_genre_from_track()")
    elif vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER IF EXISTS sync_rel_genre_from_track")
        schema_editor.execute("DROP TRIGGER IF EXISTS fill_rel_genre_from_track")
    else:
        raise NotImplementedError(f"No rel genre triggers for {vendor}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("grow", "0117_song_restricted_policy_index"),
        ("the_music_tree_genre_kit", "0015_trackplaylistrel_playlist_genre_pos_idx"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
