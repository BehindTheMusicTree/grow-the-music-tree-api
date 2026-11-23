from django.db import migrations

TABLE = "the_music_tree_genre_kit_genregraphattributionevidence"
TRIGGER = "grow_song_genre_gate"


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            f"CREATE TRIGGER {TRIGGER} BEFORE INSERT OR UPDATE OR DELETE ON {TABLE} "
            "FOR EACH STATEMENT EXECUTE FUNCTION grow_song_genre_gate()"
        )


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f"DROP TRIGGER {TRIGGER} ON {TABLE}")


class Migration(migrations.Migration):
    dependencies = [("grow", "0158_async_genre_graph_import")]
    operations = [migrations.RunPython(install, uninstall)]
