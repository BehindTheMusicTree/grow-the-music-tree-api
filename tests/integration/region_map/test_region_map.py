import gzip
import hashlib
import json
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.model.import_run.ImportRun import ImportRun
from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from grow.region_map.bulk_import.part_loader import canonical_bytes
from grow.region_map.bulk_import.RegionMapFileStaging import RegionMapFileStaging
from tests.utils.AppTestCase import AppTestCase

INDEX = reverse("region-map-index")
RUNS = INDEX + "import-runs/"
GENRE = "Q11399"
TRADITION = "Q1062400"
TILESET = "a" * 64


def _sha256(document: dict) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _index(genres: list[dict] | None = None, **overrides) -> dict:
    return {
        "regions": [
            {"itemId": "Q142", "genres": genres or [{"itemId": GENRE, "rule": "anchor", "relation": "origin"}]}
        ],
        "tileset": TILESET,
        **overrides,
    }


def _line(path: str, document: dict) -> dict:
    return {"path": path, "sha256": _sha256(document), "document": document}


def _parts(index: dict | None = None) -> list[list[dict]]:
    return [[_line("index.json", index or _index())]]


def _gzip_ndjson(lines: list[dict]) -> bytes:
    return gzip.compress("".join(json.dumps(line) + "\n" for line in lines).encode())


def _file(body: bytes) -> str:
    sha256 = hashlib.sha256(body).hexdigest()
    compressed = gzip.compress(body)
    RegionMapFile.objects.get_or_create(sha256=sha256, defaults={"body": compressed, "size": len(compressed)})
    return sha256


def _snapshot(body: bytes, hidden_body: bytes | None = None) -> RegionMapSnapshot:
    hidden_checksum = None if hidden_body is None else _file(hidden_body)
    return RegionMapSnapshot.objects.create(checksum=_file(body), hidden_regions_checksum=hidden_checksum)


DRAWN = {
    "id": "Q142",
    "name": "Europe",
    "kind": "continent",
    "genres": [{"itemId": GENRE, "rule": "anchor", "relation": "origin"}],
}
HIDDEN = {"id": "Q1", "name": "One", "kind": "admin_unit", "parentId": "world"}


def _hidden_parts(hidden: list[dict] | None = None, index: dict | None = None) -> list[list[dict]]:
    return [
        [
            _line("index.json", index or _index(regions=[DRAWN])),
            _line("hidden_regions.json", {"regions": [HIDDEN] if hidden is None else hidden}),
        ]
    ]


class TestRegionMapReads(AppTestCase):
    def setUp(self):
        super().setUp()
        self.public = APIClient()

    def test_index_without_snapshot_then_404(self):
        assert self.public.get(INDEX).status_code == status.HTTP_404_NOT_FOUND

    def test_index_served_gzip_with_etag_then_304(self):
        snapshot = _snapshot(b'{"regions":[]}')

        response = self.public.get(INDEX, HTTP_ACCEPT_ENCODING="gzip, br")

        assert response.status_code == status.HTTP_200_OK
        assert response["ETag"] == f'"{snapshot.checksum}-gzip"'
        assert response["Cache-Control"] == "no-cache"
        assert response["Content-Encoding"] == "gzip"
        assert response["Content-Type"] == "application/json"
        assert gzip.decompress(response.content) == b'{"regions":[]}'
        revalidated = self.public.get(
            INDEX, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=f'W/"{snapshot.checksum}-gzip"'
        )
        assert revalidated.status_code == status.HTTP_304_NOT_MODIFIED
        assert revalidated["ETag"] == f'"{snapshot.checksum}-gzip"'

    def test_each_encoding_revalidates_only_with_its_own_etag(self):
        snapshot = _snapshot(b'{"regions":[]}')
        plain, gzipped = f'"{snapshot.checksum}"', f'"{snapshot.checksum}-gzip"'

        identity = self.public.get(INDEX, HTTP_ACCEPT_ENCODING="identity", HTTP_IF_NONE_MATCH=gzipped)
        compressed = self.public.get(INDEX, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=plain)

        assert identity.status_code == status.HTTP_200_OK
        assert identity["ETag"] == plain
        assert identity.content == b'{"regions":[]}'
        assert compressed.status_code == status.HTTP_200_OK
        assert compressed["ETag"] == gzipped
        assert self.public.get(INDEX, HTTP_IF_NONE_MATCH=plain).status_code == status.HTTP_304_NOT_MODIFIED

    def test_gzip_follows_accept_encoding_q_values(self):
        _snapshot(b'{"regions":[]}')
        cases = {
            "gzip;q=0": False,
            "gzip;q=0, *": False,
            "br, gzip;q=0.5": True,
            "x-gzip": True,
            "*": True,
            "*;q=0": False,
            "gzip;q=abc": False,
            "deflate, br": False,
            "GZIP; Q=1": True,
        }
        for accept_encoding, gzipped in cases.items():
            with self.subTest(accept_encoding=accept_encoding):
                response = self.public.get(INDEX, HTTP_ACCEPT_ENCODING=accept_encoding)

                assert response.has_header("Content-Encoding") is gzipped

    def test_latest_snapshot_is_served(self):
        _snapshot(b'{"regions":[1]}')
        latest = _snapshot(b'{"regions":[2]}')

        assert self.public.get(INDEX)["ETag"] == f'"{latest.checksum}"'

    def test_file_route_removed(self):
        assert self.public.get(INDEX + "files/" + "0" * 64 + "/").status_code == status.HTTP_404_NOT_FOUND

    def test_viewer_cannot_create_run(self):
        assert self.public.post(path=RUNS).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.postgres
class TestRegionMapAttachable(AppTestCase):
    def test_without_snapshot_then_404(self):
        assert APIClient().get(reverse("region-map-attachable")).status_code == status.HTTP_404_NOT_FOUND

    def test_lists_drawn_then_hidden_regions(self):
        drawn = {"id": "Q1356", "name": "Maharashtra", "kind": "admin_unit", "genres": []}
        hidden = {"id": "Q18677875", "name": "Normandy", "kind": "admin_unit", "parentId": "Q142", "centroid": [1, 49]}
        _snapshot(json.dumps(_index(regions=[drawn], hiddenRegions=[hidden])).encode())

        response = APIClient().get(reverse("region-map-attachable"))

        assert response.json() == [
            {"id": "Q1356", "name": "Maharashtra", "kind": "admin_unit", "hidden": False},
            {"id": "Q18677875", "name": "Normandy", "kind": "admin_unit", "hidden": True},
        ]

    def test_lists_hidden_regions_from_their_own_file(self):
        drawn = {"id": "Q1356", "name": "Maharashtra", "kind": "admin_unit", "genres": []}
        _snapshot(json.dumps(_index(regions=[drawn])).encode(), json.dumps({"regions": [HIDDEN]}).encode())

        response = APIClient().get(reverse("region-map-attachable"))

        assert [(t["id"], t["hidden"]) for t in response.json()] == [("Q1356", False), ("Q1", True)]

    def test_index_without_hidden_regions(self):
        drawn = {"id": "Q1356", "name": "Maharashtra", "kind": "admin_unit", "genres": []}
        _snapshot(json.dumps(_index(regions=[drawn])).encode())

        assert len(APIClient().get(reverse("region-map-attachable")).json()) == 1


class TestRegionMapGenres(AppTestCase):
    URL = INDEX + "genres/"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.public = APIClient()

    def _index_with(self, *, genres: list[str], overview: str | None = None) -> None:
        region = {
            "id": "france",
            "genres": [{"itemId": item_id, "rule": "anchor", "relation": "canonical"} for item_id in genres],
            "overviewItemId": overview,
            "inheritedOverviewItemId": None,
        }
        _snapshot(json.dumps({"regions": [region], "tileset": TILESET}).encode())

    def test_without_snapshot_then_404(self):
        assert self.public.get(self.URL).status_code == status.HTTP_404_NOT_FOUND

    def test_lists_referenced_genres_only_and_skips_unknown_ids(self):
        chanson = self.model_fixture_factory.create_genre("Chanson", user=None, wikidata_id="Q1")
        self.model_fixture_factory.create_genre("Unreferenced", user=None, wikidata_id="Q2")
        self._index_with(genres=["Q1", "Q404"])

        response = self.public.get(self.URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {
                "wikidataId": "Q1",
                "uuid": str(chanson.uuid),
                "name": "Chanson",
                "treeName": CriteriaTreeName.CANONICAL,
                "genrePlaylistUuid": str(chanson.criteria_playlist.uuid),
                "isUmbrella": False,
                "viewsCount": 0,
            }
        ]

    def test_overview_is_included(self):
        self.model_fixture_factory.create_genre("Music of France", user=None, wikidata_id="Q9")
        self._index_with(genres=[], overview="Q9")

        assert [row["wikidataId"] for row in self.public.get(self.URL).json()] == ["Q9"]

    def test_conditional_response_skips_cached_payload_and_serialization(self):
        self.model_fixture_factory.create_genre("Chanson", user=None, wikidata_id="Q1")
        self._index_with(genres=["Q1"])
        initial = self.public.get(self.URL)
        cache.clear()
        with (
            patch("grow.view.region_map.cache.get", side_effect=AssertionError("must not load payload")),
            patch("grow.view.region_map.serialize_lexicon", side_effect=AssertionError("must not serialize")),
        ):
            for validator in (initial["ETag"], "W/" + initial["ETag"], '"other", ' + initial["ETag"], "*"):
                response = self.public.get(self.URL, HTTP_IF_NONE_MATCH=validator)
                assert response.status_code == status.HTTP_304_NOT_MODIFIED
                assert response.content == b""
                for header in ("ETag", "Cache-Control"):
                    assert response[header] == initial[header]

    def test_snapshot_change_invalidates_validator(self):
        self._index_with(genres=["Q1"])
        initial = self.public.get(self.URL)
        RegionMapSnapshot.objects.all().delete()
        self._index_with(genres=["Q2"])
        response = self.public.get(self.URL, HTTP_IF_NONE_MATCH=initial["ETag"])
        assert response.status_code == status.HTTP_200_OK
        assert response["ETag"] != initial["ETag"]

    def test_rename_invalidates_cached_lexicon(self):
        genre = self.model_fixture_factory.create_genre("Chanson", user=None, wikidata_id="Q1")
        self._index_with(genres=["Q1"])
        initial = self.public.get(self.URL)
        assert initial.json()[0]["name"] == "Chanson"

        type(genre).objects.update_instance(genre, actor=None, name="Chanson française")

        response = self.public.get(self.URL, HTTP_IF_NONE_MATCH=initial["ETag"])
        assert response.status_code == status.HTTP_200_OK
        assert response["ETag"] != initial["ETag"]
        assert response.json()[0]["name"] == "Chanson française"


@pytest.mark.postgres
class TestRegionMapImportRun(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)
        self.model_fixture_factory.create_genre("Rock", wikidata_id=GENRE)

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

    def test_round_trip_serves_index(self):
        result = self._sync(_parts())

        assert result == {"imported": 1, "skipped": 0}
        index = APIClient().get(INDEX)
        assert json.loads(index.content) == _index()
        assert not RegionMapFileStaging.objects.exists()
        assert not BulkImportRun.objects.exists()

    def test_wrong_sha256_then_400_and_nothing_staged(self):
        run_id = self.api_client.post(path=RUNS).data["run_id"]
        document = _index()
        invalid = [
            [{**_line("index.json", document), "sha256": _sha256({})}],
            [{**_line("index.json", document), "sha256": "nope"}],
            [{"path": "index.json", "document": document}],
            [{**_line("", document)}],
            [{**_line("index.json", document), "document": [document]}],
        ]

        codes = [self._upload(run_id, 0, lines).status_code for lines in invalid]

        assert codes == [status.HTTP_400_BAD_REQUEST] * len(invalid)
        assert not RegionMapFileStaging.objects.exists()

    def test_invalid_run_fails_and_keeps_snapshot(self):
        self._sync(_parts())
        kept = RegionMapSnapshot.objects.get()
        geometry = [*_parts()[0], _line("geometry/world.geojson", {"type": "FeatureCollection"})]
        invalid = [
            [geometry],
            [[_line("other.json", _index())]],
            _parts(_index(tileset=None)),
            _parts(_index(tileset="nope")),
            _parts(_index(files={"geometry/world.geojson": TILESET})),
        ]

        codes = [self._commit(parts).status_code for parts in invalid]

        assert codes == [status.HTTP_500_INTERNAL_SERVER_ERROR] * len(invalid)
        assert list(RegionMapSnapshot.objects.all()) == [kept]
        assert not RegionMapFileStaging.objects.exists()

    def test_unknown_genre_fails_but_tradition_allowed(self):
        unknown = [{"itemId": "Q404", "rule": "anchor", "relation": "origin"}]
        tradition = [{"itemId": TRADITION, "rule": "anchor", "relation": "tradition"}]

        assert self._commit(_parts(_index(unknown))).status_code == 500
        assert not RegionMapSnapshot.objects.exists()
        assert self._sync(_parts(_index(tradition)))["imported"] == 1

    def test_overview_item_id_must_be_a_listed_non_tradition_genre(self):
        def index(overview):
            region = {"id": "Q142", "genres": _index()["regions"][0]["genres"], "overviewItemId": overview}
            return _index(regions=[region])

        assert self._commit(_parts(index("Q404"))).status_code == 500
        assert not RegionMapSnapshot.objects.exists()
        assert self._sync(_parts(index(GENRE)))["imported"] == 1

    def test_overview_item_id_may_be_null_or_absent(self):
        region = {**_index()["regions"][0], "id": "Q142", "overviewItemId": None}

        assert self._sync(_parts(_index(regions=[region])))["imported"] == 1

    def test_missing_boundary_retains_region_and_genres(self):
        region = {
            **_index()["regions"][0],
            "id": "JO",
            "boundaryStatus": "missing",
            "bbox": None,
            "mainBbox": None,
            "centroid": None,
        }
        assert self._sync(_parts(_index(regions=[region], worldZoneIds=["JO"])))["imported"] == 1
        response = APIClient().get(INDEX)
        assert response.status_code == status.HTTP_200_OK
        assert json.loads(response.content)["regions"][0] == region

    def test_lean_region_without_boundary_status_or_main_bbox_is_kept(self):
        regions = [
            {**_index()["regions"][0], "id": "JO", "bbox": None, "centroid": None},
            {**_index()["regions"][0], "id": "FR", "bbox": [0, 0, 1, 1], "centroid": [0.5, 0.5]},
        ]
        assert self._sync(_parts(_index(regions=regions, worldZoneIds=["JO", "FR"])))["imported"] == 2
        assert json.loads(APIClient().get(INDEX).content)["regions"] == regions

    def test_boundary_status_must_agree_with_coordinates(self):
        base = {**_index()["regions"][0], "bbox": None, "mainBbox": None, "centroid": None}
        invalid = [
            {**base, "boundaryStatus": "unknown"},
            {**base, "boundaryStatus": "available"},
            {**base, "boundaryStatus": "missing", "centroid": [0, 0]},
        ]
        for region in invalid:
            assert self._commit(_parts(_index(regions=[region]))).status_code == 500
        assert not RegionMapSnapshot.objects.exists()

    def test_level_ids_must_name_existing_regions(self):
        genres = _index()["regions"][0]["genres"]
        regions = [{"id": "Q142", "genres": genres, "childIds": []}]

        assert self._commit(_parts(_index(regions=regions, worldChildIds=["Q404"]))).status_code == 500
        assert self._commit(_parts(_index(regions=regions, worldZoneIds="Q142"))).status_code == 500
        assert not RegionMapSnapshot.objects.exists()
        assert self._sync(_parts(_index(regions=regions, worldChildIds=["Q142"], worldZoneIds=[])))["imported"] == 1

    def test_city_ids_must_name_existing_regions(self):
        genres = _index()["regions"][0]["genres"]

        def index(city_ids):
            admin = {"id": "Q142", "genres": genres, "childIds": [], "cityIds": city_ids}
            return _index(regions=[admin, {"id": "Q90", "genres": genres}], worldChildIds=["Q142"])

        assert self._commit(_parts(index(["Q404"]))).status_code == 500
        assert self._commit(_parts(index("Q90"))).status_code == 500
        assert not RegionMapSnapshot.objects.exists()
        assert self._sync(_parts(index(["Q90"])))["imported"] == 2

    def test_hidden_regions_must_be_unique_undrawn_and_parented(self):
        genres = _index()["regions"][0]["genres"]
        drawn = {"id": "Q142", "genres": genres}

        def index(hidden):
            return _index(regions=[drawn], hiddenRegions=hidden)

        ok = {"id": "Q1", "name": "One", "kind": "admin_unit", "parentId": "Q142"}
        assert self._commit(_parts(index("Q1"))).status_code == 500
        assert self._commit(_parts(index([{"id": "Q142", "name": "x", "kind": "admin_unit"}]))).status_code == 500
        assert self._commit(_parts(index([ok, ok]))).status_code == 500
        assert (
            self._commit(_parts(index([{**ok, "parentId": "Q404"}, {"id": "Q9", "parentId": "world"}]))).status_code
            == 500
        )
        assert not RegionMapSnapshot.objects.exists()
        nested = [ok, {**ok, "id": "Q2", "parentId": "Q1"}, {**ok, "id": "Q3", "parentId": "world"}]
        assert self._sync(_parts(index(nested)))["imported"] == 1

    def test_delta_run_refused_at_creation(self):
        response = self.api_client.post(path=RUNS, data={"mode": "delta"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not BulkImportRun.objects.exists()

    def test_unchanged_index_skipped_and_recorded_for_pipeline_only(self):
        self._sync(_parts())
        assert not ImportRun.objects.exists()

        assert self._sync(_parts(), client=self.pipeline) == {"imported": 0, "skipped": 1}

        assert RegionMapSnapshot.objects.count() == 1
        assert RegionMapFile.objects.count() == 1
        assert list(ImportRun.objects.values_list("kind", "count", "skipped_count")) == [("region_map", 1, 1)]

    def test_changed_import_recorded_and_linked_to_snapshot(self):
        self._sync(_parts(), client=self.pipeline)

        run = ImportRun.objects.get()
        assert (run.kind, run.count, run.skipped_count) == ("region_map", 1, None)
        assert RegionMapSnapshot.objects.get().import_run == run

    def test_new_index_replaces_snapshot_and_drops_old_file(self):
        self._sync(_parts())
        self._sync(_parts(_index(tileset="b" * 64)))

        assert json.loads(APIClient().get(INDEX).content)["tileset"] == "b" * 64
        assert RegionMapSnapshot.objects.count() == 1
        assert RegionMapFile.objects.count() == 1

    def test_hidden_regions_file_imported_and_served_as_attachable(self):
        assert self._sync(_hidden_parts())["imported"] == 1

        snapshot = RegionMapSnapshot.objects.get()
        assert snapshot.hidden_regions_checksum == _sha256({"regions": [HIDDEN]})
        assert "hiddenRegions" not in json.loads(APIClient().get(INDEX).content)
        assert [t["id"] for t in APIClient().get(reverse("region-map-attachable")).json() if t["hidden"]] == ["Q1"]

    def test_previous_format_still_imported(self):
        self._sync(_parts(_index(regions=[DRAWN], hiddenRegions=[HIDDEN])))

        assert RegionMapSnapshot.objects.get().hidden_regions_checksum is None
        assert [t["id"] for t in APIClient().get(reverse("region-map-attachable")).json() if t["hidden"]] == ["Q1"]

    def test_hidden_regions_in_both_formats_refused(self):
        assert self._commit(_hidden_parts(index=_index(hiddenRegions=[HIDDEN]))).status_code == 500
        assert not RegionMapSnapshot.objects.exists()

    def test_hidden_regions_file_is_validated_like_the_inline_list(self):
        invalid = [
            [HIDDEN, HIDDEN],
            [{**HIDDEN, "parentId": "Q404"}],
            [{"id": "Q142", "name": "x", "kind": "admin_unit"}],
        ]
        for hidden in invalid:
            assert self._commit(_hidden_parts(hidden)).status_code == 500
        document = {"regions": [], "other": 1}
        assert self._commit([[*_parts()[0], _line("hidden_regions.json", document)]]).status_code == 500
        assert not RegionMapSnapshot.objects.exists()

    def test_unknown_path_refused_even_with_hidden_regions_file(self):
        parts = [[*_hidden_parts()[0], _line("other.json", _index())]]

        assert self._commit(parts).status_code == 500
        assert not RegionMapSnapshot.objects.exists()

    def test_changed_hidden_regions_replace_snapshot_for_identical_index(self):
        self._sync(_hidden_parts())
        assert self._sync(_hidden_parts(), client=self.pipeline) == {"imported": 0, "skipped": 1}

        assert self._sync(_hidden_parts([{**HIDDEN, "name": "Uno"}]))["imported"] == 1

        assert RegionMapSnapshot.objects.get().hidden_regions_checksum == _sha256(
            {"regions": [{**HIDDEN, "name": "Uno"}]}
        )
        assert RegionMapFile.objects.count() == 2
        assert [t["name"] for t in APIClient().get(reverse("region-map-attachable")).json() if t["hidden"]] == ["Uno"]

    def test_switching_formats_purges_the_old_files(self):
        self._sync(_hidden_parts())
        self._sync(_parts())

        assert RegionMapSnapshot.objects.get().hidden_regions_checksum is None
        assert RegionMapFile.objects.count() == 1
