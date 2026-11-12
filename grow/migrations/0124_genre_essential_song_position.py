import django.db.models.deletion
import the_music_tree_api_kit.field.foreign_key.PrivateManyToManyField
from django.db import migrations, models

KEY_SEPARATOR = "\t"


def backfill_positions(apps, schema_editor):
    """Orders each genre's rows by the curation rule's position (rows the rules don't name go last), then by pk."""
    Through = apps.get_model("grow", "GenreEssentialSong")
    CurationEntry = apps.get_model("grow", "CurationEntry")
    Genre = apps.get_model("grow", "Genre")
    Song = apps.get_model("grow", "Song")
    db = schema_editor.connection.alias
    rule_positions = {}
    for key, values in (
        CurationEntry.objects.using(db).filter(user=None, list_name="essential_songs").values_list("key", "values")
    ):
        item_id, _, mbid = key.partition(KEY_SEPARATOR)
        try:
            rule_positions[(item_id, mbid)] = int((values or {}).get("position"))
        except TypeError, ValueError:
            continue
    wikidata = dict(Genre.objects.using(db).values_list("pk", "wikidata_id"))
    mbids = dict(
        Song.objects.using(db)
        .filter(pk__in=Through.objects.using(db).values("song_id"))
        .values_list("pk", "musicbrainz_recording_id")
    )
    by_genre = {}
    for row in Through.objects.using(db).order_by("pk"):
        by_genre.setdefault(row.genre_id, []).append(row)
    unordered = float("inf")
    for genre_id, rows in by_genre.items():
        rows.sort(key=lambda r: rule_positions.get((wikidata.get(genre_id), str(mbids.get(r.song_id))), unordered))
        for position, row in enumerate(rows, start=1):
            Through.objects.using(db).filter(pk=row.pk).update(position=position)


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0123_curation_bot_profile"),
    ]

    operations = [
        # The auto-created through table already exists under this name: only the state changes.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="GenreEssentialSong",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                            ),
                        ),
                        ("genre", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="grow.genre")),
                        ("song", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="grow.song")),
                    ],
                    # Mirrors the auto through table's unique (genre, song), so it can be dropped below.
                    options={"db_table": "grow_genre_essential_songs", "unique_together": {("genre", "song")}},
                ),
                migrations.AlterField(
                    model_name="genre",
                    name="essential_songs",
                    field=the_music_tree_api_kit.field.foreign_key.PrivateManyToManyField.PrivateManyToManyField(
                        blank=True, related_name="essential_genres", through="grow.GenreEssentialSong", to="grow.song"
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="genreessentialsong",
            name="position",
            field=models.PositiveIntegerField(null=True),
        ),
        migrations.RunPython(backfill_positions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="genreessentialsong",
            name="position",
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterModelOptions(name="genreessentialsong", options={"ordering": ["position"]}),
        migrations.AlterUniqueTogether(name="genreessentialsong", unique_together=set()),
        migrations.AddConstraint(
            model_name="genreessentialsong",
            constraint=models.UniqueConstraint(fields=("genre", "song"), name="grow_genre_essential_song_unique"),
        ),
        migrations.AddConstraint(
            model_name="genreessentialsong",
            constraint=models.UniqueConstraint(
                fields=("genre", "position"), name="grow_genre_essential_position_unique"
            ),
        ),
    ]
