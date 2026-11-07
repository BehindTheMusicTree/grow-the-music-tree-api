from collections.abc import Iterable
from typing import Any


def genre_item_ids(index: dict[str, Any]) -> set[str]:
    """Every Wikidata id the index points at: a region's genres and the overviews standing for it."""
    item_ids: set[str] = set()
    for region in index["regions"]:
        item_ids.update(genre["itemId"] for genre in region["genres"])
        for key in ("overviewItemId", "inheritedOverviewItemId"):
            if region.get(key):
                item_ids.add(region[key])
    return item_ids


def serialize_lexicon(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "wikidataId": row["wikidata_id"],
            "uuid": str(row["uuid"]),
            "name": row["name"],
            "treeName": row["tree_name"],
            "genrePlaylistUuid": str(row["genre_playlist_uuid"]) if row["genre_playlist_uuid"] else None,
            "isUmbrella": row["is_umbrella"],
            "viewsCount": row["views_count"],
        }
        for row in rows
    ]
