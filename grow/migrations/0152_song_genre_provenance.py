from django.db import migrations

LIST = "song_genre"
LEGACY_SOURCE = "curation-legacy"
LEGACY_REASON = "Recorded before provenance was required"
DECISION_PREFIX = "legacy-song-genre:"


def fire_deferred_constraints(schema_editor):
    """Postgres refuses an ALTER TABLE on a table with pending deferred-constraint events (rows just written)."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def add_provenance(apps, schema_editor):
    """The song_genre list now carries provenance: a legacy rule gets a decision id unique to its recording, so the
    Gold re-import never registers one id with two rationales."""
    Entry = apps.get_model("grow", "CurationEntry")
    for entry in Entry.objects.filter(list_name=LIST):
        if entry.values.get("decision_id"):
            continue
        entry.values = {
            **entry.values,
            "decision_id": f"{DECISION_PREFIX}{entry.key}",
            "decision_source": LEGACY_SOURCE,
        }
        entry.reason = entry.reason or LEGACY_REASON
        entry.save(update_fields=["values", "reason"])
    fire_deferred_constraints(schema_editor)


def remove_provenance(apps, schema_editor):
    Entry = apps.get_model("grow", "CurationEntry")
    for entry in Entry.objects.filter(list_name=LIST):
        values = {k: v for k, v in entry.values.items() if k not in ("decision_id", "decision_source")}
        if values != entry.values:
            entry.values = values
            entry.save(update_fields=["values"])
    fire_deferred_constraints(schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("grow", "0151_canonical_roots_list"),
    ]

    operations = [
        migrations.RunPython(add_provenance, remove_provenance),
    ]
