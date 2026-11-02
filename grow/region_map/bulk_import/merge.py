import gzip
import json
from typing import Any

from django.db import transaction

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.merge_lock import hold_merge_lock
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.import_run.ImportRun import ImportRun
from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from grow.region_map.bulk_import.part_loader import SHA256
from grow.region_map.bulk_import.RegionMapFileStaging import RegionMapFileStaging

INDEX_PATH = "index.json"
# Tradition genres come from the genealogy, not the genre trees, so grow has no `Genre` for them.
UNRESOLVED_RELATION = "tradition"
LISTED_MAX = 20


def merge_region_map_import_run(run_id: int, user_id: int | None, record: bool) -> dict[str, Any]:
    """
    Swaps in the committed run's region map index as the only snapshot, in one transaction. The geometry is not stored
    here: the index references the immutable tileset (`tileset`, a sha256) that the pipeline published to object storage
    before this commit, so clients flip between geometry and stats atomically with the index. An index identical to the
    latest snapshot's is recorded as skipped.
    """
    with hold_merge_lock(run_id):
        try:
            return _merge(run_id, record)
        finally:
            # A failed merge rolls back, so its staged rows are dropped here instead of lingering until the next run.
            RegionMapFileStaging.objects.filter(run_id=run_id).delete()
            BulkImportDeletion.objects.filter(run_id=run_id).delete()
            BulkImportRun.objects.filter(pk=run_id).delete()


def _listed(values: set[str]) -> str:
    return ", ".join(sorted(values)[:LISTED_MAX]) + (" …" if len(values) > LISTED_MAX else "")


def _staged_hashes(run_id: int) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path, sha256 in RegionMapFileStaging.objects.filter(run_id=run_id).values_list("path", "sha256"):
        if path in hashes:
            raise ValueError(f"import run {run_id} stages {path} twice")
        hashes[path] = sha256
    return hashes


def _check_index(index: Any) -> None:
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
        for genre in region["genres"]:
            if not isinstance(genre, dict) or not isinstance(genre.get("itemId"), str):
                raise ValueError("each region genre must be an object with an itemId")
            if genre.get("relation") != UNRESOLVED_RELATION:
                item_ids.add(genre["itemId"])
    if unknown := item_ids - set(Genre.objects.filter(wikidata_id__in=item_ids).values_list("wikidata_id", flat=True)):
        raise ValueError(f"region genres missing from grow: {_listed(unknown)}")


def _merge(run_id: int, record: bool) -> dict[str, Any]:
    paths = _staged_hashes(run_id)
    if extra := paths.keys() - {INDEX_PATH}:
        raise ValueError(f"import run {run_id} uploads files other than {INDEX_PATH}: {_listed(extra)}")
    if INDEX_PATH not in paths:
        raise ValueError(f"import run {run_id} has no {INDEX_PATH}")
    checksum = paths[INDEX_PATH]
    staged = RegionMapFileStaging.objects.get(run_id=run_id, path=INDEX_PATH)
    index = json.loads(gzip.decompress(staged.body))
    _check_index(index)
    count = len(index["regions"])
    latest = RegionMapSnapshot.objects.first()
    unchanged = latest is not None and latest.checksum == checksum
    with transaction.atomic():
        run = None
        if record:
            run = ImportRun.objects.create(
                kind=ImportRun.Kind.REGION_MAP, count=count, skipped_count=count if unchanged else None
            )
        if unchanged:
            return {"imported": 0, "skipped": count}
        RegionMapFile.objects.bulk_create(
            [RegionMapFile(sha256=checksum, body=staged.body, size=len(staged.body))], ignore_conflicts=True
        )
        # Only the latest index is served; the tilesets it references are immutable and live in object storage.
        RegionMapSnapshot.objects.all().delete()
        RegionMapSnapshot.objects.create(checksum=checksum, import_run=run)
        RegionMapFile.objects.exclude(sha256=checksum).delete()
    return {"imported": count, "skipped": 0}
