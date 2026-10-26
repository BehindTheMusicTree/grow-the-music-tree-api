import django.db.models.deletion
from django.contrib.postgres.operations import TrigramExtension, UnaccentExtension
from django.db import migrations, models

# `unaccent` is only STABLE, so an index can't use it directly; this wrapper pins the dictionary, which is what makes it
# safe to declare IMMUTABLE. Search queries must call it too, or the trigram indexes aren't used.
CREATE_SEARCH_NORM = """CREATE OR REPLACE FUNCTION grow_search_norm(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT lower(unaccent('unaccent'::regdictionary, $1)) $$"""
DROP_SEARCH_NORM = "DROP FUNCTION IF EXISTS grow_search_norm(text)"


def _create_search_norm(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_SEARCH_NORM)


def _drop_search_norm(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_SEARCH_NORM)


class Migration(migrations.Migration):

    dependencies = [
        ("grow", "0068_curation_drop_derived_labels"),
    ]

    operations = [
        TrigramExtension(),
        UnaccentExtension(),
        migrations.RunPython(_create_search_norm, _drop_search_norm),
        migrations.AddField(
            model_name="artist",
            name="disambiguation",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="artist",
            name="recording_count",
            field=models.PositiveIntegerField(db_default=0),
        ),
        migrations.CreateModel(
            name="ArtistAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.TextField()),
                (
                    "artist",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="aliases", to="grow.artist"
                    ),
                ),
            ],
            options={
                "db_table": "grow_artist_alias",
                "constraints": [models.UniqueConstraint(fields=("artist", "name"), name="grow_artist_alias_unique")],
            },
        ),
    ]
