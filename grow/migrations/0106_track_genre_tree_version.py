from django.db import migrations

TABLE = "the_music_tree_genre_kit_track"
TRIGGER = "bump_genre_tree_version_track_genre"


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            f"CREATE TRIGGER {TRIGGER} AFTER UPDATE OF genre_id, user_id ON {TABLE} "
            "FOR EACH STATEMENT EXECUTE FUNCTION bump_genre_tree_version()"
        )
    elif schema_editor.connection.vendor == "sqlite":
        schema_editor.execute(
            f"CREATE TRIGGER {TRIGGER} AFTER UPDATE OF genre_id, user_id ON {TABLE} "
            "WHEN OLD.genre_id IS NOT NEW.genre_id OR OLD.user_id IS NOT NEW.user_id BEGIN "
            "UPDATE grow_genre_tree_version SET token = lower(hex(randomblob(16))) WHERE id = 1; END"
        )
    else:
        raise NotImplementedError(f"No genre tree version trigger for {schema_editor.connection.vendor}")


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON {TABLE}")
    elif schema_editor.connection.vendor == "sqlite":
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {TRIGGER}")
    else:
        raise NotImplementedError(f"No genre tree version trigger for {schema_editor.connection.vendor}")


class Migration(migrations.Migration):
    dependencies = [("grow", "0105_alter_curationentry_list_name_and_more")]

    operations = [migrations.RunPython(create_trigger, drop_trigger)]
