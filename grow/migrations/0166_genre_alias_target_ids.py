from django.db import migrations

# Resolved from the staging and prod Wikidata Silver output (read-only VPS reads, 2026-11-25). The label is the one
# stored on the entry, which Wikidata has since renamed for Q7309098.
TARGETS = {
    "aor": ("album-oriented rock", "Q428656"),
    "neo-traditional country": ("neotraditional country", "Q458480"),
    "oi": ("oi!", "Q274401"),
    "regional mexicano": ("regional Mexican", "Q7309098"),
    "romantic classical": ("Romantic music", "Q207591"),
}


def fill_targets(apps, schema_editor):
    entries = apps.get_model("grow", "CurationEntry").objects.filter(list_name="genre_alias", user=None)
    for entry in entries:
        if entry.values.get("target_item_id"):
            continue
        expected = TARGETS.get(entry.key)
        if expected is None or entry.values.get("wikidata_genre_name") != expected[0]:
            raise RuntimeError(f"genre_alias {entry.key!r} has no target id and no known one to fill it with")
        entry.values = {**entry.values, "target_item_id": expected[1]}
        entry.save(update_fields=["values"])


class Migration(migrations.Migration):
    dependencies = [("grow", "0165_drop_alias_legacy_unmigrated")]

    operations = [migrations.RunPython(fill_targets, migrations.RunPython.noop)]
