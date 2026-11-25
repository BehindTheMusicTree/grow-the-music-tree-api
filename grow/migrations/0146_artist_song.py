import django.db.models.deletion
from django.db import migrations, models

# Postgres-only: the keyset indexes carry the sort direction and NULLS LAST. `rebuild_artist_song` recreates every
# index of the table from `pg_indexes`, so these need no second definition there.
POSTGRES_INDEXES = {
    "grow_artist_song_title_idx": "CREATE INDEX CONCURRENTLY grow_artist_song_title_idx ON grow_artist_song (artist_id, title, song_id)",
    "grow_artist_song_year_idx": (
        "CREATE INDEX CONCURRENTLY grow_artist_song_year_idx ON grow_artist_song"
        " (artist_id, album_year DESC NULLS LAST, song_id DESC)"
    ),
}
SETTINGS = (
    "autovacuum_vacuum_scale_factor = 0, autovacuum_vacuum_threshold = 200000, autovacuum_analyze_scale_factor = 0,"
    " autovacuum_analyze_threshold = 100000, autovacuum_vacuum_insert_scale_factor = 0,"
    " autovacuum_vacuum_insert_threshold = 200000"
)


def _create_postgres_objects(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for sql in POSTGRES_INDEXES.values():
            schema_editor.execute(sql)
        # Absolute thresholds, like migration 0066: at tens of millions of rows the default scale factors never fire.
        schema_editor.execute(f"ALTER TABLE grow_artist_song SET ({SETTINGS})")


def _drop_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for name in POSTGRES_INDEXES:
            schema_editor.execute(f"DROP INDEX IF EXISTS {name}")


class Migration(migrations.Migration):
    atomic = False  # CREATE INDEX CONCURRENTLY cannot run inside a transaction

    dependencies = [
        ("grow", "0145_song_genre_undo"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArtistSongState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ready", models.BooleanField(default=False)),
                ("rebuilt_on", models.DateTimeField(null=True)),
            ],
            options={"db_table": "grow_artist_song_state"},
        ),
        migrations.CreateModel(
            name="ArtistSong",
            fields=[
                ("pk", models.CompositePrimaryKey("artist", "song", blank=True, editable=False, primary_key=True, serialize=False)),
                ("title", models.TextField()),
                ("album_year", models.SmallIntegerField(null=True)),
                (
                    "artist",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="grow.artist",
                    ),
                ),
                (
                    "song",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="grow.song",
                    ),
                ),
            ],
            options={"db_table": "grow_artist_song"},
        ),
        migrations.RunPython(_create_postgres_objects, _drop_postgres_indexes),
    ]
