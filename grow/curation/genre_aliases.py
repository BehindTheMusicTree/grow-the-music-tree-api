import hashlib
import json
from datetime import datetime
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException, ValidationError
from the_music_tree_genre_kit.genre_graph.models import GenreGraphDataset

from grow.curation.lists import GENRE_ALIAS_LIST
from grow.curation.rows import lock_writes
from grow.genre_graph.service import DATASET_KEY
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationExport import CurationExport
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.curation.CurationSyncState import CurationSyncState


class AliasCatalogueUnavailable(APIException):
    status_code = 503
    default_detail = "The genre alias catalogue has not been published yet"


def alias_catalogue() -> dict[str, Any]:
    publication = CurationSyncState.load().genre_alias_publication
    if publication is None:
        raise AliasCatalogueUnavailable
    return publication


def search_alias_targets(query: str, limit: int) -> dict[str, Any]:
    catalogue = alias_catalogue()
    q = query.casefold()
    results = [
        target for target in catalogue["targets"] if target["id"].casefold() == q or q in target["label"].casefold()
    ]
    results.sort(
        key=lambda target: (
            target["id"].casefold() != q,
            target["label"].casefold() != q,
            target["label"].casefold(),
            target["id"],
        )
    )
    return {
        "published_on": catalogue["published_on"],
        "curation_exported_on": catalogue["curation_exported_on"],
        "results": results[:limit],
    }


def prepare_alias_write(row: dict[str, Any], entry: CurationEntry | None = None) -> dict[str, Any]:
    lock_writes(CurationEntry.objects.filter(user=None))
    old = entry.row if entry else {}
    old_id = old.get("target_item_id", "")
    old_label = old.get("wikidata_genre_name", "")
    target_id = row.get("target_item_id", old_id)
    label = row.get("wikidata_genre_name", old_label)
    key_changed = entry is None or row.get("musicbrainz_genre_name", entry.key) != entry.key
    legacy_create = entry is None and bool(label)
    if "target_item_id" in row and not target_id and (old_id or (entry is None and not legacy_create)):
        raise ValidationError({"row": {"target_item_id": "Select a target by id"}})
    if entry and target_id == old_id and label == old_label and not key_changed:
        return {**old, **row}

    targets = alias_catalogue()["targets"]
    legacy_retarget = target_id == old_id and label != old_label
    if target_id and not legacy_retarget:
        candidates = [target for target in targets if target["id"] == target_id]
    else:
        candidates = [target for target in targets if target["label"] == label]
    if len(candidates) != 1:
        raise ValidationError({"row": {"target_item_id": "Select one eligible target by id"}})
    target = candidates[0]
    return {**old, **row, "target_item_id": target["id"], "wikidata_genre_name": target["label"]}


def alias_revision(entry: CurationEntry) -> list[str]:
    return [str(entry.uuid), (entry.updated_on or entry.created_on).isoformat()]


def apply_alias_report(exported_on: datetime, report: dict[str, Any], count: int) -> bool:
    """Apply a report inside the transaction that records the ImportRun."""
    lock_catalogue_sources()
    dataset = GenreGraphDataset.objects.select_for_update().filter(pk=DATASET_KEY).first()
    entries = CurationEntry.objects.filter(user=None, list_name=GENRE_ALIAS_LIST)
    lock_writes(entries)
    state = CurationSyncState.objects.select_for_update().get(pk=CurationSyncState.load().pk)
    current = state.genre_alias_publication
    digest = hashlib.sha256(
        json.dumps({"report": report, "count": count}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if current:
        current_export = datetime.fromisoformat(current["curation_exported_on"])
        if exported_on < current_export:
            return False
        if exported_on == current_export:
            if digest != current["digest"]:
                raise ValidationError({"genre_alias_review": "Different report already recorded for this export"})
            return False

    export = CurationExport.objects.filter(exported_on=exported_on).first()
    if (
        export is None
        or not export.snapshot
        or export.snapshot.get("genre_alias_version") != 2
        or export.genre_alias_revisions is None
        or state.applied_export_on != exported_on
    ):
        raise ValidationError({"genre_alias_review": "Report must reference the applied v2 curation export"})

    graph_export = dataset.payload.get("curationExportedOn") if dataset else None
    if not isinstance(graph_export, str) or parse_datetime(graph_export) != exported_on:
        raise ValidationError({"genre_alias_review": "Report must reference the published reference graph export"})

    by_tag = {row["musicbrainz_genre_name"]: row for row in export.snapshot[GENRE_ALIAS_LIST]}
    live = {entry.key: alias_revision(entry) for entry in entries}
    reviews = []
    for issue in report["issues"]:
        tag = issue["tag"]
        row = by_tag.get(tag)
        target_id = issue.get("target_item_id")
        if (
            row is None
            or target_id != (row["target_item_id"] or None)
            or issue.get("last_known_label") != row["wikidata_genre_name"]
        ):
            raise ValidationError({"genre_alias_review": f"Issue does not match the exported rule for {tag}"})
        if live.get(tag) != export.genre_alias_revisions[tag]:
            continue
        reviews.append(
            CurationReviewItem(
                list_name=GENRE_ALIAS_LIST,
                key=tag,
                column="target_item_id",
                item_id=target_id or "",
                reason=issue["reason"],
                evidence={
                    "label": row["wikidata_genre_name"],
                    "entry_uuid": live[tag][0],
                    "exposure": issue["exposure"],
                    "alias": issue["evidence"],
                },
            )
        )
    CurationReviewItem.objects.filter(reason__in=CurationReviewItem.GENRE_ALIAS_REASONS).delete()
    CurationReviewItem.objects.bulk_create(reviews)
    state.genre_alias_publication = {
        "digest": digest,
        "curation_exported_on": exported_on.isoformat(),
        "published_on": timezone.now().isoformat(),
        "targets": report["targets"],
    }
    state.save(update_fields=["genre_alias_publication"])
    return True
