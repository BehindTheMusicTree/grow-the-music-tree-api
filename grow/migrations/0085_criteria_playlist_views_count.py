from importlib import import_module

from django.db import migrations, models

REL = "the_music_tree_genre_kit_track_playlist_rel"

POSTGRES_FUNCTIONS = f"""
CREATE FUNCTION views_count_rel_insert() RETURNS trigger AS $$
BEGIN
    UPDATE grow_criteria_playlist cp SET views_count = cp.views_count + d.v
    FROM (
        SELECT n.playlist_id, sum(coalesce(s.youtube_view_count, 0)) AS v
        FROM new_rows n JOIN grow_song s ON s.track_id = n.track_id GROUP BY n.playlist_id
    ) d
    WHERE cp.playlist_id = d.playlist_id AND d.v <> 0;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Relies on a rel being deleted before its song: the songs merge and Django's cascade both do.
CREATE FUNCTION views_count_rel_delete() RETURNS trigger AS $$
BEGIN
    UPDATE grow_criteria_playlist cp SET views_count = cp.views_count - d.v
    FROM (
        SELECT o.playlist_id, sum(coalesce(s.youtube_view_count, 0)) AS v
        FROM old_rows o JOIN grow_song s ON s.track_id = o.track_id GROUP BY o.playlist_id
    ) d
    WHERE cp.playlist_id = d.playlist_id AND d.v <> 0;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION views_count_rel_truncate() RETURNS trigger AS $$
BEGIN
    UPDATE grow_criteria_playlist SET views_count = 0 WHERE views_count <> 0;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION views_count_song_update() RETURNS trigger AS $$
BEGIN
    UPDATE grow_criteria_playlist cp SET views_count = cp.views_count + d.v
    FROM (
        SELECT r.playlist_id,
            sum(coalesce(n.youtube_view_count, 0) - coalesce(o.youtube_view_count, 0)) AS v
        FROM new_rows n
        JOIN old_rows o ON o.track_id = n.track_id
        JOIN {REL} r ON r.track_id = n.track_id
        WHERE n.youtube_view_count IS DISTINCT FROM o.youtube_view_count
        GROUP BY r.playlist_id
    ) d
    WHERE cp.playlist_id = d.playlist_id AND d.v <> 0;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

# Transition tables cannot be combined with several events or a column list, so one trigger per event.
POSTGRES_TRIGGERS = f"""
CREATE TRIGGER views_count_rel_insert AFTER INSERT ON {REL}
    REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION views_count_rel_insert();
CREATE TRIGGER views_count_rel_delete AFTER DELETE ON {REL}
    REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION views_count_rel_delete();
CREATE TRIGGER views_count_rel_truncate AFTER TRUNCATE ON {REL}
    FOR EACH STATEMENT EXECUTE FUNCTION views_count_rel_truncate();
CREATE TRIGGER views_count_song_update AFTER UPDATE ON grow_song
    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION views_count_song_update();
"""

POSTGRES_BACKFILL = f"""
UPDATE grow_criteria_playlist cp SET views_count = s.v
FROM (
    SELECT r.playlist_id, sum(coalesce(g.youtube_view_count, 0)) AS v
    FROM {REL} r JOIN grow_song g ON g.track_id = r.track_id GROUP BY r.playlist_id
) s
WHERE cp.playlist_id = s.playlist_id
"""

SQLITE_BACKFILL = f"""
UPDATE grow_criteria_playlist SET views_count = coalesce((
    SELECT sum(coalesce(g.youtube_view_count, 0)) FROM {REL} r JOIN grow_song g ON g.track_id = r.track_id
    WHERE r.playlist_id = grow_criteria_playlist.playlist_id
), 0)
"""

# SQLite has no statement-level triggers; row-level ones keep the test suite checking the same invariant.
SQLITE_TRIGGERS = [
    f"""CREATE TRIGGER views_count_rel_insert AFTER INSERT ON {REL} BEGIN
        UPDATE grow_criteria_playlist SET views_count = views_count + coalesce(
            (SELECT youtube_view_count FROM grow_song WHERE track_id = NEW.track_id), 0
        ) WHERE playlist_id = NEW.playlist_id;
    END""",
    f"""CREATE TRIGGER views_count_rel_delete AFTER DELETE ON {REL} BEGIN
        UPDATE grow_criteria_playlist SET views_count = views_count - coalesce(
            (SELECT youtube_view_count FROM grow_song WHERE track_id = OLD.track_id), 0
        ) WHERE playlist_id = OLD.playlist_id;
    END""",
    """CREATE TRIGGER views_count_song_update AFTER UPDATE OF youtube_view_count ON grow_song BEGIN
        UPDATE grow_criteria_playlist
        SET views_count = views_count + coalesce(NEW.youtube_view_count, 0) - coalesce(OLD.youtube_view_count, 0)
        WHERE playlist_id IN (SELECT playlist_id FROM """
    + REL
    + """ WHERE track_id = NEW.track_id);
    END""",
]


def _restored_tree_version_triggers() -> list[str]:
    # SQLite's AddField rebuilds the table, dropping the genre tree version triggers 0039 put on it.
    tree_version = import_module("grow.migrations.0039_genre_tree_version")
    table = "grow_criteria_playlist"
    drops = [f"DROP TRIGGER IF EXISTS bump_genre_tree_version_{table}_{op}" for op in ("insert", "update", "delete")]
    return [*drops, *tree_version._sqlite_triggers(table)]


def create_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        statements = [POSTGRES_BACKFILL, POSTGRES_FUNCTIONS, POSTGRES_TRIGGERS]
    elif vendor == "sqlite":
        statements = [SQLITE_BACKFILL, *SQLITE_TRIGGERS, *_restored_tree_version_triggers()]
    else:
        raise NotImplementedError(f"No views count triggers for {vendor}")
    for sql in statements:
        schema_editor.execute(sql)


def drop_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(f"DROP TRIGGER IF EXISTS views_count_rel_insert ON {REL}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS views_count_rel_delete ON {REL}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS views_count_rel_truncate ON {REL}")
        schema_editor.execute("DROP TRIGGER IF EXISTS views_count_song_update ON grow_song")
        for function in ("rel_insert", "rel_delete", "rel_truncate", "song_update"):
            schema_editor.execute(f"DROP FUNCTION IF EXISTS views_count_{function}()")
    elif vendor == "sqlite":
        for trigger in ("views_count_rel_insert", "views_count_rel_delete", "views_count_song_update"):
            schema_editor.execute(f"DROP TRIGGER IF EXISTS {trigger}")


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0084_alter_genre_summary_source_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="criteriaplaylist",
            name="views_count",
            field=models.PositiveBigIntegerField(default=0, db_default=0),
        ),
        migrations.RunPython(create_triggers, drop_triggers),
    ]
