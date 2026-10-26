import json
from collections.abc import Iterable
from typing import Any

from grow.curation.lists import ADDITION_LABEL_COLUMN, ADDITION_LISTS, ITEM_ID_COLUMNS
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.WikidataItem import WikidataItem


def item_ids(rows: Iterable[dict[str, Any]]) -> set[str]:
    return {str(v) for row in rows for c, v in row.items() if c in ITEM_ID_COLUMNS and v}


def snapshot_item_ids(snapshots: Iterable[str | None]) -> set[str]:
    """Item ids held by history snapshots (JSON objects of a row)."""
    return item_ids(json.loads(s) for s in snapshots if s)


def resolve_item_labels(ids: set[str]) -> dict[str, str]:
    """Name of each item id, from the canonical tree, else the pipeline's Wikidata catalog, else the name an admin
    gave the item when adding it (an addition not imported yet). An id with no source is absent."""
    if not ids:
        return {}
    labels: dict[str, str] = {}
    added = CurationEntry.objects.filter(user=None, list_name__in=ADDITION_LISTS, key__in=ids)
    for entry in added:
        if label := entry.values.get(ADDITION_LABEL_COLUMN):
            labels[entry.key] = label
    labels.update(WikidataItem.objects.filter(item_id__in=ids).values_list("item_id", "label"))
    labels.update(Genre.objects.filter(user=None, wikidata_id__in=ids).values_list("wikidata_id", "_name"))
    return labels
