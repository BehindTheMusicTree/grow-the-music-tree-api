from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def rename_index_forwards(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER INDEX IF EXISTS "playlist_user_uuid_idx" RENAME TO "grow_playlist_user_uuid_idx";')


def rename_index_backwards(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER INDEX IF EXISTS "grow_playlist_user_uuid_idx" RENAME TO "playlist_user_uuid_idx";')


class Migration(migrations.Migration):
    """
    0001_initial was hand-edited (see 3dc6993) to rename this index from `playlist_user_uuid_idx`
    to `grow_playlist_user_uuid_idx`, avoiding a name collision with the kit's own
    `playlist_user_uuid_idx` on its new Playlist table (0004_playlist). Editing an already-applied
    migration file only affects fresh databases — any database that had already run the original
    0001_initial (staging, production) still physically carries the old index name, so the kit's
    0004_playlist crashes with a duplicate-index error on first boot after this file changed.

    This can't be a `RenameIndex` operation: Django builds migration state purely from the
    migration history, and `0001_initial` already declares the index under its new name, so a
    `RenameIndex` here would always fail state-building with "no index named
    playlist_user_uuid_idx" (fresh databases and the test suite included). `RunPython` renames the
    physical index directly, without touching Django's model state, is a no-op on any database
    created straight from the edited 0001_initial (`IF EXISTS`), and is skipped entirely on SQLite
    (used by the test suite), which has no `ALTER INDEX` statement and never carried the old name.

    `run_before` forces this onto every environment ahead of the kit's 0004_playlist, regardless
    of when it was created.
    """

    dependencies = [
        ("grow", "0007_delete_grow_track"),
    ]

    run_before = [
        ("the_music_tree_genre_kit", "0004_playlist"),
    ]

    operations = [
        migrations.RunPython(rename_index_forwards, rename_index_backwards),
    ]
