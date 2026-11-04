from importlib import import_module

from django.db import migrations, models

VIEWS_COUNT = import_module("grow.migrations.0085_criteria_playlist_views_count")


def drop_views_count_triggers(apps, schema_editor):
    # SQLite's AddField rebuilds grow_criteria_playlist, which fails while other tables' triggers write to it.
    if schema_editor.connection.vendor == "sqlite":
        VIEWS_COUNT.drop_triggers(apps, schema_editor)


def recreate_playlist_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        return
    for sql in [*VIEWS_COUNT.SQLITE_TRIGGERS, *VIEWS_COUNT._restored_tree_version_triggers()]:
        schema_editor.execute(sql)


def backfill(apps, schema_editor):
    from grow.track.direct_songs_count import recount_direct_songs_count

    recount_direct_songs_count(apps.get_model("grow", "Song"), apps.get_model("grow", "CriteriaPlaylist"))


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0092_song_import_staging_genre_wikidata_id"),
    ]

    operations = [
        migrations.RunPython(drop_views_count_triggers, recreate_playlist_triggers),
        migrations.AddField(
            model_name="criteriaplaylist",
            name="direct_songs_count",
            field=models.IntegerField(default=0, db_default=0),
        ),
        migrations.RunPython(recreate_playlist_triggers, drop_views_count_triggers),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
