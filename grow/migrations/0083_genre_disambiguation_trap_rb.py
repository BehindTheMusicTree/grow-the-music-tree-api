from django.db import migrations

REASON = "ambiguous MusicBrainz tag resolved per song from its other genres"

DISAMBIGUATION = [
    ("r&b", "Q45981", True),
    ("r&b", "Q850412", False),
    ("trap", "Q2913982", True),
    ("trap", "Q47781397", False),
]

CONTEXT = [
    ("r&b", "Q45981", "Q9759"),
    ("r&b", "Q45981", "Q8341"),
    ("trap", "Q47781397", "Q851213"),
]


def seed(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    rows = [
        ("genre_disambiguation", (name, item_id), {"is_default": is_default})
        for name, item_id, is_default in DISAMBIGUATION
    ] + [("genre_disambiguation_context", key, {}) for key in CONTEXT]
    for list_name, key_parts, values in rows:
        key = "\t".join(key_parts)
        entries = CurationEntry.objects.filter(user=None, list_name=list_name, key=key)
        if not entries.update(values=values, reason=REASON):
            CurationEntry.objects.create(user=None, list_name=list_name, key=key, values=values, reason=REASON)


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0082_core_electronic_scene_split"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
