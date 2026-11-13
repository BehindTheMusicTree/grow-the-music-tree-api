import gzip
import json
from typing import Any

from django.db import transaction

from grow.bulk_import.lifecycle import execute_merge
from grow.bulk_import.progress import report_step
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.import_run.ImportRun import ImportRun
from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from grow.region_map.bulk_import.part_loader import SHA256
from grow.region_map.bulk_import.RegionMapFileStaging import RegionMapFileStaging
from grow.schemas import first_error

INDEX_PATH = "index.json"
# Hidden regions are curation-only targets, so they ship beside the index instead of inflating the map's document.
HIDDEN_REGIONS_PATH = "hidden_regions.json"
# Curation-only too: the import signal for `CurationReviewItem`, never served, so it must not travel in the index.
OVERVIEW_ALERTS_PATH = "synthesized_overview_alerts.json"
# Each file is checked against the Gold schema of the same name (`grow/schemas/`), which also keeps the served index
# byte-for-byte within the strict client schema. Tradition genres come from the genealogy, not the genre trees, so grow
# has no `Genre` for them.
SCHEMA_NAMES = {
    INDEX_PATH: "region_map",
    HIDDEN_REGIONS_PATH: "hidden_regions",
    OVERVIEW_ALERTS_PATH: "synthesized_overview_alerts",
}
UNRESOLVED_RELATION = "tradition"
LISTED_MAX = 20
_ALERT_PREFIX = "synthetic_overview_"


def merge_region_map_import_run(
    run_id: int, user_id: int | None, record: bool, attempt_id: int | None = None
) -> dict[str, Any]:
    """
    Swaps in the committed run's region map index as the only snapshot, in one transaction. The geometry is not stored
    here: the index references the immutable tileset (`tileset`, a sha256) that the pipeline published to object storage
    before this commit, so clients flip between geometry and stats atomically with the index. An index identical to the
    latest snapshot's is recorded as skipped. A run carries exactly three files: the index, `hidden_regions.json` (the
    attachable targets kept out of the map) and `synthesized_overview_alerts.json` (only feeds the curation review items).
    """
    return execute_merge(run_id, attempt_id, RegionMapFileStaging, lambda: _merge(run_id, record))


def _listed(values: set[str]) -> str:
    return ", ".join(sorted(values)[:LISTED_MAX]) + (" …" if len(values) > LISTED_MAX else "")


def _staged_hashes(run_id: int) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path, sha256 in RegionMapFileStaging.objects.filter(run_id=run_id).values_list("path", "sha256"):
        if path in hashes:
            raise ValueError(f"import run {run_id} stages {path} twice")
        hashes[path] = sha256
    return hashes


def _load(run_id: int, path: str) -> Any:
    document = json.loads(gzip.decompress(RegionMapFileStaging.objects.get(run_id=run_id, path=path).body))
    if error := first_error(SCHEMA_NAMES[path], document):
        raise ValueError(f"{path} violates its Gold schema: {error}")
    return document


def _check_index(index: dict[str, Any], hidden: list[dict[str, Any]]) -> None:
    """What the schema cannot say: references between regions, and against grow's own genres."""
    item_ids: set[str] = set()
    for region in index["regions"]:
        listed = {genre["itemId"] for genre in region["genres"] if genre["relation"] != UNRESOLVED_RELATION}
        item_ids |= listed
        overview = region["overviewItemId"]
        if overview is not None and overview not in listed:
            raise ValueError(
                f"region {region['id']} overviewItemId {overview!r} must be one of its non-tradition genres"
            )
    _check_level_ids(index)
    _check_hidden_regions(index, hidden)
    if unknown := item_ids - set(Genre.objects.filter(wikidata_id__in=item_ids).values_list("wikidata_id", flat=True)):
        raise ValueError(f"region genres missing from grow: {_listed(unknown)}")


def _replace_overview_alerts(alerts: list[dict[str, Any]]) -> None:
    CurationReviewItem.objects.filter(reason__in=CurationReviewItem.SYNTHETIC_OVERVIEW_REASONS).delete()
    CurationReviewItem.objects.bulk_create(
        [
            CurationReviewItem(
                column="item_id",
                item_id=alert["itemId"],
                reason=_ALERT_PREFIX + alert["reason"],
                target_item_id=alert["targetItemId"],
                evidence={"regionId": alert["regionId"]},
            )
            for alert in alerts
        ]
    )


def _check_level_ids(index: dict[str, Any]) -> None:
    """Every level a region (or the world) opens onto must name regions that exist, so a click never drills nowhere."""
    region_ids = {region["id"] for region in index["regions"]}
    for owner, key, ids in [
        *((r["id"], key, r[key]) for r in index["regions"] for key in ("childIds", "zoneIds", "cityIds") if key in r),
        *(("world", key, index[key]) for key in ("worldChildIds", "worldZoneIds")),
    ]:
        if missing := set(ids) - region_ids:
            raise ValueError(f"{owner} {key} name unknown regions: {_listed(missing)}")


def _check_hidden_regions(index: dict[str, Any], hidden: list[dict[str, Any]]) -> None:
    """Hidden regions are attachable targets kept out of the map: unique ids, never shadowing a drawn region."""
    region_ids = {region["id"] for region in index["regions"]}
    hidden_ids: set[str] = set()
    for region in hidden:
        if region["id"] in hidden_ids:
            raise ValueError(f"hidden region {region['id']} is listed twice")
        hidden_ids.add(region["id"])
    if both := hidden_ids & region_ids:
        raise ValueError(f"hidden regions are also drawn regions: {_listed(both)}")
    for region in hidden:
        parent = region["parentId"]
        if parent != "world" and parent not in region_ids | hidden_ids:
            raise ValueError(f"hidden region {region['id']} parentId {parent!r} is unknown")


def _merge(run_id: int, record: bool) -> dict[str, Any]:
    paths = _staged_hashes(run_id)
    if paths.keys() != set(SCHEMA_NAMES):
        raise ValueError(
            f"import run {run_id} must upload exactly {_listed(set(SCHEMA_NAMES))}, got {_listed(set(paths)) or 'nothing'}"
        )
    checksum, hidden_checksum = paths[INDEX_PATH], paths[HIDDEN_REGIONS_PATH]
    with report_step("validate_index"):
        index = _load(run_id, INDEX_PATH)
        hidden = _load(run_id, HIDDEN_REGIONS_PATH)["regions"]
        alerts = _load(run_id, OVERVIEW_ALERTS_PATH)["alerts"]
        _check_index(index, hidden)
    count = len(index["regions"])
    latest = RegionMapSnapshot.objects.first()
    unchanged = latest is not None and (latest.checksum, latest.hidden_regions_checksum) == (checksum, hidden_checksum)
    with report_step("publish_snapshot"), transaction.atomic():
        run = None
        if record:
            run = ImportRun.objects.create(
                kind=ImportRun.Kind.REGION_MAP, count=count, skipped_count=count if unchanged else None
            )
        _replace_overview_alerts(alerts)
        if unchanged:
            return {"imported": 0, "skipped": count}
        files = [
            (paths[path], RegionMapFileStaging.objects.get(run_id=run_id, path=path).body)
            for path in (INDEX_PATH, HIDDEN_REGIONS_PATH)
        ]
        RegionMapFile.objects.bulk_create(
            [RegionMapFile(sha256=sha, body=body, size=len(body)) for sha, body in files], ignore_conflicts=True
        )
        # Only the latest index is served; the tilesets it references are immutable and live in object storage.
        RegionMapSnapshot.objects.all().delete()
        RegionMapSnapshot.objects.create(checksum=checksum, hidden_regions_checksum=hidden_checksum, import_run=run)
        RegionMapFile.objects.exclude(sha256__in=[sha for sha, _ in files]).delete()
    return {"imported": count, "skipped": 0}
