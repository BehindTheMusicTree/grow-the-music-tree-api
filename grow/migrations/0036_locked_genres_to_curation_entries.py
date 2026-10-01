from django.db import migrations

from grow.curation.lists import EXCLUSIVE_LISTS
from grow.curation.rows import upsert_without_history

REASON = "migrated grow admin lock"


def _rules(genre, actions: set[str], parent_item_id: str | None) -> list[tuple[str, dict[str, str]]]:
    """The curation rows reproducing a genre's admin edits, told apart by its admin history trail. Edits no
    list can express (a reparent to a root, to an app-created parent, or in the regional tree) stay lock-only."""
    item = {"item_id": genre.wikidata_id}
    rules = []
    if "root_accepted" in actions and not genre.is_unaccepted_root:
        rules.append(("accepted_canonical_roots", {**item, "item_label": genre._name}))
    if "renamed" in actions:
        rules.append(("label_overrides", {**item, "display_label": genre._name, "reason": REASON}))
    if "parent_changed" in actions and genre.tree_name == "canonical" and parent_item_id is not None:
        row = {**item, "item_label": genre._name, "reason": REASON}
        rules.append(("main_parent", {**row, "parent_item_id": parent_item_id, "exclude_other_parents": "true"}))
    if "excluded" in actions and genre.is_excluded:
        # The exclusion's category was never recorded: out_of_scope_genres is the catch-all.
        rules.append(("out_of_scope_genres", {**item, "item_label": genre._name, "reason": REASON}))
    return rules


def locked_genres_to_curation_entries(apps, schema_editor):
    Genre = apps.get_model("grow", "Genre")
    HistoryEntry = apps.get_model("grow", "HistoryEntry")
    CurationEntry = apps.get_model("grow", "CurationEntry")
    admin_actions: dict = {}
    for content_uuid, action in HistoryEntry.objects.filter(
        content_type__app_label="grow", content_type__model="genre", actor__isnull=False
    ).values_list("content_uuid", "action"):
        admin_actions.setdefault(content_uuid, set()).add(action)
    genres = Genre.objects.filter(user=None, wikidata_id__isnull=False, uuid__in=admin_actions).exclude(
        is_manually_edited=False, is_excluded=False
    )
    for genre in genres:
        parent_item_id = Genre.objects.filter(pk=genre.parent_id).values_list("wikidata_id", flat=True).first()
        for list_name, row in _rules(genre, admin_actions[genre.uuid], parent_item_id):
            if list_name in EXCLUSIVE_LISTS and CurationEntry.objects.filter(
                user=None, list_name__in=EXCLUSIVE_LISTS, key=genre.wikidata_id
            ).exists():
                continue
            upsert_without_history(CurationEntry, list_name, row)


class Migration(migrations.Migration):
    dependencies = [("grow", "0035_seed_curation_entries")]

    operations = [migrations.RunPython(locked_genres_to_curation_entries, migrations.RunPython.noop)]
