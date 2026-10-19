from django.db import migrations, models

OLD_LIST = "regional_secondary_parents"
NEW_LIST = "secondary_parents"


def move_to_secondary_parents(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    for entry in CurationEntry.objects.filter(list_name=OLD_LIST):
        entry.list_name = NEW_LIST
        entry.values = {**entry.values, "action": "add"}
        entry.save(update_fields=["list_name", "values"])


class Migration(migrations.Migration):

    dependencies = [
        ("grow", "0057_curation_review_item"),
    ]

    operations = [
        migrations.AlterField(
            model_name="curationentry",
            name="list_name",
            field=models.CharField(choices=[('accepted_canonical_roots', 'accepted_canonical_roots'), ('canonical_parent_additions', 'canonical_parent_additions'), ('capitalized_words', 'capitalized_words'), ('duplicate_genres', 'duplicate_genres'), ('indigenous_to_exclusions', 'indigenous_to_exclusions'), ('label_overrides', 'label_overrides'), ('main_parent', 'main_parent'), ('out_of_scope_genres', 'out_of_scope_genres'), ('overview_reclassifications', 'overview_reclassifications'), ('regional_overrides', 'regional_overrides'), ('regional_overview_additions', 'regional_overview_additions'), ('technique_genres', 'technique_genres'), ('theme_genres', 'theme_genres'), ('umbrella_canonical_genres', 'umbrella_canonical_genres'), ('accepted_non_genre_tags', 'accepted_non_genre_tags'), ('canonical_genre_pop_side', 'canonical_genre_pop_side'), ('genre_alias', 'genre_alias'), ('secondary_parents', 'secondary_parents'), ('recording_genre', 'recording_genre'), ('recording_youtube_video', 'recording_youtube_video'), ('essential_tracks', 'essential_tracks'), ('summary_overrides', 'summary_overrides'), ('genre_precedence', 'genre_precedence')], max_length=64),
        ),
        migrations.RunPython(move_to_secondary_parents, migrations.RunPython.noop),
    ]
