import gzip
import json
from typing import Any

from django.db import transaction
from django.db.models import Exists, OuterRef

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.merge_lock import hold_merge_lock
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.import_run.ImportRun import ImportRun
from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from grow.model.region_map.RegionMapSnapshotFile import RegionMapSnapshotFile
from grow.region_map.bulk_import.part_loader import SHA256
from grow.region_map.bulk_import.RegionMapFileStaging import RegionMapFileStaging

INDEX_PATH = "index.json"
# A client that loaded the previous index keeps finding its files while it renders.
SNAPSHOTS_KEPT = 2
# Tradition genres come from the genealogy, not the genre trees, so grow has no `Genre` for them.
UNRESOLVED_RELATION = "tradition"
LISTED_MAX = 20


def merge_region_map_import_run(run_id: int, user_id: int | None, record: bool) -> dict[str, Any]:
    """
    Swaps in the committed run's region map as the new snapshot, in one transaction: its new files stored, the
    snapshot created, all but the last `SNAPSHOTS_KEPT` snapshots dropped with every file no snapshot lists any more.
    An index identical to the latest snapshot's is recorded as skipped.
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


def _check_index(index: Any, files: dict[str, str]) -> None:
    if not isinstance(index, dict) or not isinstance(index.get("regions"), list):
        raise ValueError("index must be an object with a regions list")
    listed = index.get("files")
    if not isinstance(listed, dict) or not all(
        isinstance(sha256, str) and SHA256.fullmatch(sha256) for sha256 in listed.values()
    ):
        raise ValueError("index files must map each path to its sha256")
    if missing := listed.keys() - files.keys():
        raise ValueError(f"index lists files the run did not upload: {_listed(missing)}")
    if extra := files.keys() - listed.keys():
        raise ValueError(f"run uploads files the index does not list: {_listed(extra)}")
    if mismatched := {path for path, sha256 in listed.items() if files[path] != sha256}:
        raise ValueError(f"index sha256 differs from the uploaded file: {_listed(mismatched)}")
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
    if BulkImportRun.objects.get(pk=run_id).mode != BulkImportRun.Mode.FULL:
        raise ValueError(f"import run {run_id} must be full: a region map snapshot is always whole")
    files = _staged_hashes(run_id)
    if INDEX_PATH not in files:
        raise ValueError(f"import run {run_id} has no {INDEX_PATH}")
    checksum = files.pop(INDEX_PATH)
    index_body = RegionMapFileStaging.objects.get(run_id=run_id, path=INDEX_PATH).body
    _check_index(json.loads(gzip.decompress(index_body)), files)
    latest = RegionMapSnapshot.objects.first()
    unchanged = latest is not None and latest.checksum == checksum
    with transaction.atomic():
        run = None
        if record:
            run = ImportRun.objects.create(
                kind=ImportRun.Kind.REGION_MAP, count=len(files), skipped_count=len(files) if unchanged else None
            )
        if unchanged:
            return {"imported": 0, "skipped": len(files)}
        stored = set(
            RegionMapFile.objects.filter(sha256__in=[checksum, *files.values()]).values_list("sha256", flat=True)
        )
        RegionMapFile.objects.bulk_create(
            [
                RegionMapFile(sha256=sha256, body=body, size=len(body))
                for sha256, body in RegionMapFileStaging.objects.filter(run_id=run_id)
                .exclude(sha256__in=stored)
                .values_list("sha256", "body")
                .iterator()
            ],
            ignore_conflicts=True,
        )
        # A snapshot re-imported after a newer one moves back to the front instead of colliding on its checksum.
        RegionMapSnapshot.objects.filter(checksum=checksum).delete()
        snapshot = RegionMapSnapshot.objects.create(checksum=checksum, import_run=run)
        RegionMapSnapshotFile.objects.bulk_create(
            RegionMapSnapshotFile(snapshot=snapshot, path=path, file_id=sha256)
            for path, sha256 in {INDEX_PATH: checksum, **files}.items()
        )
        RegionMapSnapshot.objects.exclude(
            pk__in=list(RegionMapSnapshot.objects.values_list("pk", flat=True)[:SNAPSHOTS_KEPT])
        ).delete()
        RegionMapFile.objects.filter(~Exists(RegionMapSnapshotFile.objects.filter(file=OuterRef("pk")))).delete()
    return {"imported": len(files), "skipped": 0}
