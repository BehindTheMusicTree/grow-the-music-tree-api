import logging
import re
import unicodedata

from django.db import migrations

logger = logging.getLogger(__name__)

ADDITIONS = "canonical_parent_additions"
ADDITION_LISTS = (ADDITIONS, "regional_overview_additions")
# Lists whose keys are `LOCAL:` ids a new node must not reuse.
IDENTITY_LISTS = (*ADDITION_LISTS, "local_identities", "canonical_roots")
SCENE_LIST = "canonical_genre_scene"
REASON = "grow migration: app-created genre adopted as a node"


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower())
    return slug.strip("-") or "genre"


def adopt_admin_genres(apps, schema_editor):
    """Gives every canonical genre created in the admin without a wikidata id the same `LOCAL:` node a new admin
    genre now gets (see `GenreManager._adopt_created`), so the next reference graph sync maps it instead of failing on
    an unmapped genre. Written with the historical models: no manager, actor or `HistoryEntry` (nobody acts here, and
    the history model is not part of this state's contract). A genre with no adoptable ancestry down to a wikidata
    item is skipped and logged, not invented a parent."""
    Genre = apps.get_model("grow", "Genre")
    Entry = apps.get_model("grow", "CurationEntry")
    Rule = apps.get_model("grow", "GenreEdgeRule")

    taken = set(Entry.objects.filter(user=None, list_name__in=IDENTITY_LISTS).values_list("key", flat=True))
    taken |= set(Genre.objects.filter(wikidata_id__startswith="LOCAL:").values_list("wikidata_id", flat=True))

    pending = list(
        Genre.objects.filter(
            user=None,
            tree_name="canonical",
            is_excluded=False,
            wikidata_id__isnull=True,
            semantic_identity__isnull=True,
        ).order_by("created_on", "pk")
    )
    # Only canonical, non-excluded genres can parent a new node (the admin refuses the others the same way).
    item_ids = {
        pk: wikidata_id
        for pk, wikidata_id in Genre.objects.filter(
            wikidata_id__isnull=False, tree_name="canonical", is_excluded=False
        ).values_list("pk", "wikidata_id")
    }
    # A genre with a scene child is a scene split: a new, scene-less node can't sit directly under it.
    scene_keys = set(Entry.objects.filter(user=None, list_name=SCENE_LIST).values_list("key", flat=True))
    split_parents = {
        parent
        for item, parent in Rule.objects.filter(user=None, relation="canonical_parent").values_list(
            "item_id", "parent_item_id"
        )
        if item in scene_keys
    }

    # Parents before children: a pass adopts every pending genre whose parent already has an item id.
    while pending:
        remaining = []
        for genre in pending:
            parent_item_id = item_ids.get(genre.parent_id) if genre.parent_id is not None else None
            if parent_item_id is None:
                remaining.append(genre)
                continue
            if parent_item_id in split_parents:
                logger.warning(
                    "Genre %r (%s) left unadopted: its parent %s is split into scenes",
                    genre._name,
                    genre.uuid,
                    parent_item_id,
                )
                continue
            item_id, n = f"LOCAL:{slugify(genre._name)}", 1
            base = item_id
            while item_id in taken:
                n += 1
                item_id = f"{base}-{n}"
            taken.add(item_id)
            Entry.objects.create(
                user=None, list_name=ADDITIONS, key=item_id, values={"label": genre._name}, reason=REASON
            )
            Rule.objects.create(
                user=None,
                relation="canonical_parent",
                item_id=item_id,
                parent_item_id=parent_item_id,
                exclude_other_parents=True,
                reason=REASON,
            )
            Genre.objects.filter(pk=genre.pk).update(wikidata_id=item_id, is_manually_edited=True)
            item_ids[genre.pk] = item_id
        if len(remaining) == len(pending):
            for genre in remaining:
                logger.warning(
                    "Genre %r (%s) left unadopted: no parent chain down to a pipeline item", genre._name, genre.uuid
                )
            return
        pending = remaining


class Migration(migrations.Migration):
    dependencies = [
        ("grow", "0153_genre_derivations_list"),
    ]

    operations = [
        # Not reversible in a meaningful way: adopted genres can't be told from ones that were mapped by hand.
        migrations.RunPython(adopt_admin_genres, migrations.RunPython.noop),
    ]
