import logging

from django.db import migrations

logger = logging.getLogger(__name__)

SEPARATOR = "\t"


def _qid_by_name(apps) -> dict[str, str]:
    Genre = apps.get_model("grow", "Genre")
    CurationEntry = apps.get_model("grow", "CurationEntry")
    by_name = {
        name.lower(): qid
        for name, qid in Genre.objects.filter(user=None, tree_name="canonical", wikidata_id__isnull=False).values_list(
            "_name", "wikidata_id"
        )
    }
    for entry in CurationEntry.objects.filter(user=None, list_name="genre_alias"):
        qid = by_name.get(entry.values["wikidata_genre_name"].lower())
        if qid is not None:
            by_name.setdefault(entry.key.lower(), qid)
    return by_name


def convert_precedence(apps, schema_editor):
    CurationEntry = apps.get_model("grow", "CurationEntry")
    Genre = apps.get_model("grow", "Genre")
    entries = list(CurationEntry.objects.filter(list_name="genre_precedence"))
    if not entries:
        return
    qids = _qid_by_name(apps)
    if not qids:
        CurationEntry.objects.filter(list_name="genre_precedence").delete()
        return

    unresolved = sorted(
        {name for e in entries for name in e.key.split(SEPARATOR) if name.lower() not in qids},
    )
    if unresolved:
        raise RuntimeError(f"genre_precedence names with no canonical genre or alias: {unresolved}")

    genres = {g.wikidata_id: g for g in Genre.objects.filter(user=None, tree_name="canonical", wikidata_id__in=qids.values())}
    converted: set[str] = set()
    for entry in entries:
        winner, loser = (qids[name.lower()] for name in entry.key.split(SEPARATOR))
        key = f"{winner}{SEPARATOR}{loser}"
        in_lineage = (
            genres[winner].ascendants.filter(pk=genres[loser].pk).exists()
            or genres[loser].ascendants.filter(pk=genres[winner].pk).exists()
        )
        if in_lineage or key in converted:
            logger.warning("Dropping genre_precedence %s: already in a genre lineage or duplicated", entry.key)
            entry.delete()
            continue
        converted.add(key)
        entry.key = key
        entry.save(update_fields=["key"])


def rename_umbrella_list(apps, schema_editor):
    for model in ("CurationEntry", "CurationReviewItem"):
        apps.get_model("grow", model).objects.filter(list_name="umbrella_canonical_genres").update(
            list_name="non_stylistic_genres"
        )


def restore_umbrella_list(apps, schema_editor):
    for model in ("CurationEntry", "CurationReviewItem"):
        apps.get_model("grow", model).objects.filter(list_name="non_stylistic_genres").update(
            list_name="umbrella_canonical_genres"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0064_genre_is_umbrella_curation_lists"),
    ]

    operations = [
        migrations.RunPython(rename_umbrella_list, restore_umbrella_list),
        migrations.RunPython(convert_precedence, migrations.RunPython.noop),
    ]
