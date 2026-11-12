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

INDEX_PATH = "index.json"
# Hidden regions are curation-only targets, so they ship beside the index instead of inflating the map's document.
HIDDEN_REGIONS_PATH = "hidden_regions.json"
# Tradition genres come from the genealogy, not the genre trees, so grow has no `Genre` for them.
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
    latest snapshot's is recorded as skipped. The hidden regions (attachable targets kept out of the map) come either as
    `hidden_regions.json` or, in the previous format, as the index's `hiddenRegions`, never both.
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


def _check_index(index: Any, hidden: Any) -> None:
    if not isinstance(index, dict) or not isinstance(index.get("regions"), list):
        raise ValueError("index must be an object with a regions list")
    if not isinstance(index.get("tileset"), str) or not SHA256.fullmatch(index["tileset"]):
        raise ValueError("index tileset must be the sha256 of the published tileset")
    if "files" in index:
        raise ValueError("index must not list files: the geometry is the tileset")
    item_ids: set[str] = set()
    for region in index["regions"]:
        if not isinstance(region, dict) or not isinstance(region.get("genres"), list):
            raise ValueError("each region must be an object with a genres list")
        _check_boundary(region)
        listed: set[str] = set()
        for genre in region["genres"]:
            if not isinstance(genre, dict) or not isinstance(genre.get("itemId"), str):
                raise ValueError("each region genre must be an object with an itemId")
            if genre.get("relation") != UNRESOLVED_RELATION:
                listed.add(genre["itemId"])
        item_ids |= listed
        # Optional until the pipeline publishes it: the schema accepts indexes from before `overviewItemId` existed.
        overview = region.get("overviewItemId")
        if overview is not None and overview not in listed:
            raise ValueError(
                f"region {region.get('id')} overviewItemId {overview!r} must be one of its non-tradition genres"
            )
    _check_level_ids(index)
    _check_overview_alerts(index)
    _check_hidden_regions(index, hidden)
    if unknown := item_ids - set(Genre.objects.filter(wikidata_id__in=item_ids).values_list("wikidata_id", flat=True)):
        raise ValueError(f"region genres missing from grow: {_listed(unknown)}")


def _check_overview_alerts(index: dict[str, Any]) -> None:
    """The alerts are optional until the pipeline publishes them; each needs the `LOCAL:` id and a known reason."""
    alerts = index.get("synthesizedOverviewAlerts", [])
    if not isinstance(alerts, list):
        raise ValueError("synthesizedOverviewAlerts must be a list")
    reasons = {reason.removeprefix(_ALERT_PREFIX) for reason in CurationReviewItem.SYNTHETIC_OVERVIEW_REASONS}
    for alert in alerts:
        if (
            not isinstance(alert, dict)
            or not isinstance(alert.get("itemId"), str)
            or alert.get("reason") not in reasons
            or not isinstance(alert.get("targetItemId"), str | None)
        ):
            raise ValueError("each synthesized overview alert needs a string itemId, a known reason and a targetItemId")


def _replace_overview_alerts(index: dict[str, Any]) -> None:
    CurationReviewItem.objects.filter(reason__in=CurationReviewItem.SYNTHETIC_OVERVIEW_REASONS).delete()
    CurationReviewItem.objects.bulk_create(
        [
            CurationReviewItem(
                column="item_id",
                item_id=alert["itemId"],
                reason=_ALERT_PREFIX + alert["reason"],
                target_item_id=alert["targetItemId"],
                evidence={"regionId": alert.get("regionId")},
            )
            for alert in index.get("synthesizedOverviewAlerts", [])
        ]
    )


def _check_boundary(region: dict[str, Any]) -> None:
    """A region without a boundary has null coordinates, all together; `boundaryStatus` is optional but must agree.

    The lean index omits `boundaryStatus` (null `bbox` says it) and `mainBbox` when it equals `bbox`.
    """
    declared = "boundaryStatus" in region
    status = region.get("boundaryStatus")
    if declared and status not in ("available", "missing"):
        raise ValueError("region boundaryStatus must be available or missing")
    if (declared or any(key in region for key in ("bbox", "mainBbox", "centroid"))) and not all(
        k in region for k in ("bbox", "centroid")
    ):
        raise ValueError("a region boundary requires bbox and centroid coordinates, null when it has none")
    coordinates = [region[key] for key in ("bbox", "mainBbox", "centroid") if key in region]
    unset = [value is None for value in coordinates]
    if any(unset) and not all(unset):
        raise ValueError("boundary coordinates must be all null (no boundary) or all set")
    if declared and (status == "missing") != all(unset):
        raise ValueError("region boundaryStatus disagrees with its coordinates")


def _check_level_ids(index: dict[str, Any]) -> None:
    """Every level a region (or the world) opens onto must name regions that exist, so a click never drills nowhere."""
    region_ids = {region["id"] for region in index["regions"] if "id" in region}
    for owner, key, ids in [
        *(
            (r["id"], key, r[key])
            for r in index["regions"]
            if "id" in r
            for key in ("childIds", "zoneIds", "cityIds")
            if key in r
        ),
        *(("world", key, index[key]) for key in ("worldChildIds", "worldZoneIds") if key in index),
    ]:
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError(f"{owner} {key} must be a list of region ids")
        if missing := set(ids) - region_ids:
            raise ValueError(f"{owner} {key} name unknown regions: {_listed(missing)}")


def _check_hidden_regions(index: dict[str, Any], hidden: Any) -> None:
    """Hidden regions are attachable targets kept out of the map: unique ids, never shadowing a drawn region."""
    if not isinstance(hidden, list):
        raise ValueError("hidden regions must be a list")
    region_ids = {region["id"] for region in index["regions"] if "id" in region}
    hidden_ids: set[str] = set()
    for region in hidden:
        if not isinstance(region, dict) or not all(isinstance(region.get(key), str) for key in ("id", "name", "kind")):
            raise ValueError("each hidden region must be an object with a string id, name and kind")
        if region["id"] in hidden_ids:
            raise ValueError(f"hidden region {region['id']} is listed twice")
        hidden_ids.add(region["id"])
    if both := hidden_ids & region_ids:
        raise ValueError(f"hidden regions are also drawn regions: {_listed(both)}")
    for region in hidden:
        parent = region.get("parentId")
        if parent is not None and parent != "world" and parent not in region_ids | hidden_ids:
            raise ValueError(f"hidden region {region['id']} parentId {parent!r} is unknown")


def _hidden_regions(run_id: int, index: Any, hidden_checksum: str | None) -> Any:
    """The run's hidden regions: from its own file, or from the index in the previous format."""
    has_inline = isinstance(index, dict) and "hiddenRegions" in index
    if hidden_checksum is None:
        return index.get("hiddenRegions", []) if isinstance(index, dict) else []
    if has_inline:
        raise ValueError(f"import run {run_id} has hidden regions in both {INDEX_PATH} and {HIDDEN_REGIONS_PATH}")
    body = RegionMapFileStaging.objects.get(run_id=run_id, path=HIDDEN_REGIONS_PATH).body
    document = json.loads(gzip.decompress(body))
    if not isinstance(document, dict) or set(document) != {"regions"}:
        raise ValueError(f"{HIDDEN_REGIONS_PATH} must be an object with only a regions list")
    return document["regions"]


def _merge(run_id: int, record: bool) -> dict[str, Any]:
    paths = _staged_hashes(run_id)
    if extra := paths.keys() - {INDEX_PATH, HIDDEN_REGIONS_PATH}:
        raise ValueError(
            f"import run {run_id} uploads files other than {INDEX_PATH} and {HIDDEN_REGIONS_PATH}: {_listed(extra)}"
        )
    if INDEX_PATH not in paths:
        raise ValueError(f"import run {run_id} has no {INDEX_PATH}")
    checksum = paths[INDEX_PATH]
    hidden_checksum = paths.get(HIDDEN_REGIONS_PATH)
    staged = RegionMapFileStaging.objects.get(run_id=run_id, path=INDEX_PATH)
    index = json.loads(gzip.decompress(staged.body))
    with report_step("validate_index"):
        _check_index(index, _hidden_regions(run_id, index, hidden_checksum))
    count = len(index["regions"])
    latest = RegionMapSnapshot.objects.first()
    unchanged = latest is not None and (latest.checksum, latest.hidden_regions_checksum) == (checksum, hidden_checksum)
    with report_step("publish_snapshot"), transaction.atomic():
        run = None
        if record:
            run = ImportRun.objects.create(
                kind=ImportRun.Kind.REGION_MAP, count=count, skipped_count=count if unchanged else None
            )
        _replace_overview_alerts(index)
        if unchanged:
            return {"imported": 0, "skipped": count}
        files = [(checksum, staged.body)]
        if hidden_checksum is not None:
            files.append(
                (hidden_checksum, RegionMapFileStaging.objects.get(run_id=run_id, path=HIDDEN_REGIONS_PATH).body)
            )
        RegionMapFile.objects.bulk_create(
            [RegionMapFile(sha256=sha, body=body, size=len(body)) for sha, body in files], ignore_conflicts=True
        )
        # Only the latest index is served; the tilesets it references are immutable and live in object storage.
        RegionMapSnapshot.objects.all().delete()
        RegionMapSnapshot.objects.create(checksum=checksum, hidden_regions_checksum=hidden_checksum, import_run=run)
        RegionMapFile.objects.exclude(sha256__in=[sha for sha, _ in files]).delete()
    return {"imported": count, "skipped": 0}
