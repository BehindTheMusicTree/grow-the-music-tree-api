import gzip
import hashlib
import json

import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.model.import_run.ImportRun import ImportRun
from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from grow.model.region_map.RegionMapSnapshotFile import RegionMapSnapshotFile
from grow.region_map.bulk_import.part_loader import canonical_bytes
from grow.region_map.bulk_import.RegionMapFileStaging import RegionMapFileStaging
from tests.utils.AppTestCase import AppTestCase

INDEX = reverse("region-map-index")
RUNS = INDEX + "import-runs/"
GENRE = "Q11399"
TRADITION = "Q1062400"
WORLD = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"id": "world"}}]}
FRANCE = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"id": "Q142"}}]}


def _sha256(document: dict) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _index(files: dict[str, dict], genres: list[dict] | None = None) -> dict:
    return {
        "regions": [
            {"itemId": "Q142", "genres": genres or [{"itemId": GENRE, "rule": "anchor", "relation": "origin"}]}
        ],
        "files": {path: _sha256(document) for path, document in files.items()},
    }


def _line(path: str, document: dict) -> dict:
    return {"path": path, "sha256": _sha256(document), "document": document}


def _parts(files: dict[str, dict], index: dict | None = None) -> list[list[dict]]:
    return [[_line(path, document) for path, document in files.items()], [_line("index.json", index or _index(files))]]


def _gzip_ndjson(lines: list[dict]) -> bytes:
    return gzip.compress("".join(json.dumps(line) + "\n" for line in lines).encode())


def _snapshot(files: dict[str, bytes]) -> RegionMapSnapshot:
    stored = {path: hashlib.sha256(body).hexdigest() for path, body in files.items()}
    for path, body in files.items():
        compressed = gzip.compress(body)
        RegionMapFile.objects.get_or_create(sha256=stored[path], defaults={"body": compressed, "size": len(compressed)})
    snapshot = RegionMapSnapshot.objects.create(checksum=stored["index.json"])
    RegionMapSnapshotFile.objects.bulk_create(
        RegionMapSnapshotFile(snapshot=snapshot, path=path, file_id=sha256) for path, sha256 in stored.items()
    )
    return snapshot


class TestRegionMapReads(AppTestCase):
    def setUp(self):
        super().setUp()
        self.public = APIClient()

    def test_index_without_snapshot_then_404(self):
        assert self.public.get(INDEX).status_code == status.HTTP_404_NOT_FOUND

    def test_index_served_gzip_with_etag_then_304(self):
        snapshot = _snapshot({"index.json": b'{"regions":[]}'})

        response = self.public.get(INDEX, HTTP_ACCEPT_ENCODING="gzip, br")

        assert response.status_code == status.HTTP_200_OK
        assert response["ETag"] == f'"{snapshot.checksum}"'
        assert response["Cache-Control"] == "no-cache"
        assert response["Content-Encoding"] == "gzip"
        assert response["Content-Type"] == "application/json"
        assert gzip.decompress(response.content) == b'{"regions":[]}'
        revalidated = self.public.get(INDEX, HTTP_IF_NONE_MATCH=f'W/"{snapshot.checksum}"')
        assert revalidated.status_code == status.HTTP_304_NOT_MODIFIED

    def test_latest_snapshot_is_served(self):
        _snapshot({"index.json": b'{"regions":[1]}'})
        latest = _snapshot({"index.json": b'{"regions":[2]}'})

        assert self.public.get(INDEX)["ETag"] == f'"{latest.checksum}"'

    def test_file_immutable_and_inflated_without_gzip(self):
        _snapshot({"index.json": b"{}", "geometry/world.geojson": b'{"type":"FeatureCollection"}'})
        sha256 = hashlib.sha256(b'{"type":"FeatureCollection"}').hexdigest()
        path = reverse("region-map-file", args=[sha256])

        response = self.public.get(path, HTTP_ACCEPT="application/geo+json")

        assert response.status_code == status.HTTP_200_OK
        assert response["Cache-Control"] == "public, max-age=31536000, immutable"
        assert response["Content-Type"] == "application/geo+json"
        assert "Accept-Encoding" in response["Vary"]
        assert not response.has_header("Content-Encoding")
        assert response.content == b'{"type":"FeatureCollection"}'
        assert self.public.get(path, HTTP_ACCEPT_ENCODING="gzip")["Content-Encoding"] == "gzip"

    def test_unknown_file_then_404(self):
        assert self.public.get(reverse("region-map-file", args=["0" * 64])).status_code == status.HTTP_404_NOT_FOUND

    def test_viewer_cannot_create_run(self):
        assert self.public.post(path=RUNS).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.postgres
class TestRegionMapImportRun(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)
        self.model_fixture_factory.create_genre("Rock", wikidata_id=GENRE)
        self.files = {"geometry/world.geojson": WORLD, "geometry/Q142.geojson": FRANCE}

    def _upload(self, run_id: int, part: int, lines: list[dict], client=None):
        return (client or self.api_client).put(
            path=f"{RUNS}{run_id}/parts/{part}/",
            data=_gzip_ndjson(lines),
            format=None,
            content_type="application/x-ndjson",
            HTTP_CONTENT_ENCODING="gzip",
        )

    def _commit(self, parts: list[list[dict]], client=None, mode: str = "full"):
        client = client or self.api_client
        run_id = client.post(path=RUNS, data={"mode": mode}).data["run_id"]
        for part, lines in enumerate(parts):
            response = self._upload(run_id, part, lines, client)
            assert response.status_code == status.HTTP_200_OK, response.content
        return client.post(path=f"{RUNS}{run_id}/commit/")

    def _sync(self, parts: list[list[dict]], client=None) -> dict:
        response = self._commit(parts, client)
        assert response.status_code == status.HTTP_202_ACCEPTED
        task = self.api_client.get(path=INDEX + f"import/{response.data['task_id']}/status/")
        assert task.data["status"] == "success", task.data
        return task.data["result"]

    def test_round_trip_serves_index_and_files(self):
        result = self._sync(_parts(self.files))

        assert result["imported"] == 2
        index = APIClient().get(INDEX)
        assert json.loads(index.content) == _index(self.files)
        file = APIClient().get(reverse("region-map-file", args=[_sha256(FRANCE)]))
        assert json.loads(file.content) == FRANCE
        assert not RegionMapFileStaging.objects.exists()
        assert not BulkImportRun.objects.exists()

    def test_wrong_sha256_then_400_and_nothing_staged(self):
        run_id = self.api_client.post(path=RUNS).data["run_id"]
        invalid = [
            [{**_line("geometry/world.geojson", WORLD), "sha256": _sha256(FRANCE)}],
            [{**_line("geometry/world.geojson", WORLD), "sha256": "nope"}],
            [{"path": "geometry/world.geojson", "document": WORLD}],
            [{**_line("", WORLD)}],
            [{**_line("geometry/world.geojson", WORLD), "document": [WORLD]}],
        ]

        codes = [self._upload(run_id, 0, lines).status_code for lines in invalid]

        assert codes == [status.HTTP_400_BAD_REQUEST] * len(invalid)
        assert not RegionMapFileStaging.objects.exists()

    def test_index_and_upload_mismatch_fails_and_keeps_snapshot(self):
        self._sync(_parts(self.files))
        kept = RegionMapSnapshot.objects.get()
        missing = _parts({"geometry/world.geojson": WORLD}, _index(self.files))
        extra = _parts(self.files, _index({"geometry/world.geojson": WORLD}))
        no_index = [_parts(self.files)[0]]

        codes = [self._commit(parts).status_code for parts in (missing, extra, no_index)]

        assert codes == [status.HTTP_500_INTERNAL_SERVER_ERROR] * 3
        assert list(RegionMapSnapshot.objects.all()) == [kept]
        assert not RegionMapFileStaging.objects.exists()

    def test_unknown_genre_fails_but_tradition_allowed(self):
        unknown = [{"itemId": "Q404", "rule": "anchor", "relation": "origin"}]
        tradition = [{"itemId": TRADITION, "rule": "anchor", "relation": "tradition"}]

        assert self._commit(_parts(self.files, _index(self.files, unknown))).status_code == 500
        assert not RegionMapSnapshot.objects.exists()
        assert self._sync(_parts(self.files, _index(self.files, tradition)))["imported"] == 2

    def test_delta_run_fails(self):
        assert self._commit(_parts(self.files), mode="delta").status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert not RegionMapSnapshot.objects.exists()

    def test_unchanged_index_skipped_and_recorded_for_pipeline_only(self):
        self._sync(_parts(self.files))
        assert not ImportRun.objects.exists()

        assert self._sync(_parts(self.files), client=self.pipeline) == {"imported": 0, "skipped": 2}

        assert RegionMapSnapshot.objects.count() == 1
        assert list(ImportRun.objects.values_list("kind", "count", "skipped_count")) == [("region_map", 2, 2)]

    def test_changed_import_recorded_and_linked_to_snapshot(self):
        self._sync(_parts(self.files), client=self.pipeline)

        run = ImportRun.objects.get()
        assert (run.kind, run.count, run.skipped_count) == ("region_map", 2, None)
        assert RegionMapSnapshot.objects.get().import_run == run

    def test_keeps_previous_snapshot_files_and_drops_older(self):
        versions = [{**self.files, "geometry/Q142.geojson": {**FRANCE, "version": n}} for n in range(3)]
        for files in versions:
            self._sync(_parts(files))

        france = {_sha256(files["geometry/Q142.geojson"]) for files in versions}
        stored = set(RegionMapFile.objects.values_list("sha256", flat=True))
        assert RegionMapSnapshot.objects.count() == 2
        assert france - stored == {_sha256(versions[0]["geometry/Q142.geojson"])}
        assert _sha256(WORLD) in stored
        assert RegionMapFile.objects.count() == 2 * 2 + 1
