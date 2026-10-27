from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from grow.model.genealogy.GenealogySnapshot import GenealogySnapshot
from grow.model.import_run.ImportRun import ImportRun
from tests.utils.AppTestCase import AppTestCase

TRADITION = {
    "wikidataId": "Q1",
    "label": "Blues",
    "start": 1890,
    "end": None,
    "anchorId": "Q2",
    "inCanonicalTree": True,
}
DOCUMENT = {
    "columns": [{"position": 0, "startYear": 1800}],
    "bands": [{"columnId": "c0", "fragmentId": "b0"}],
    "successions": [],
    "traditions": [TRADITION],
    "traditionLinks": [{"sourceId": "Q1", "targetId": "Q2"}],
}


class TestGenealogy(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)
        self.import_url = reverse("genealogy-import")
        self.url = reverse("genealogy")

    def test_pipeline_import_then_stored_verbatim_and_run_recorded(self):
        response = self.pipeline.post(self.import_url, DOCUMENT, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        snapshot = GenealogySnapshot.objects.get()
        assert snapshot.document == DOCUMENT
        assert snapshot.checksum == response.json()["checksum"]
        assert list(ImportRun.objects.values_list("kind", "count", "skipped_count")) == [("genealogy", 1, None)]
        assert snapshot.import_run == ImportRun.objects.get()

    def test_same_document_twice_then_no_second_snapshot(self):
        self.pipeline.post(self.import_url, DOCUMENT, format="json")

        response = self.pipeline.post(self.import_url, {**DOCUMENT}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["created"] is False
        assert GenealogySnapshot.objects.count() == 1
        assert list(ImportRun.objects.order_by("pk").values_list("count", "skipped_count")) == [(1, None), (1, 1)]

    def test_changed_document_then_new_snapshot(self):
        self.pipeline.post(self.import_url, DOCUMENT, format="json")

        changed = {**DOCUMENT, "traditions": [{**TRADITION, "label": "Delta blues"}]}
        assert self.pipeline.post(self.import_url, changed, format="json").status_code == status.HTTP_201_CREATED

        assert GenealogySnapshot.objects.count() == 2

    def test_invalid_shape_then_400_and_nothing_stored(self):
        for body in (
            {k: v for k, v in DOCUMENT.items() if k != "bands"},
            {**DOCUMENT, "columns": {}},
            {**DOCUMENT, "traditions": [{**TRADITION, "label": None}]},
            {**DOCUMENT, "traditions": [{"wikidataId": "Q1"}]},
            [],
        ):
            assert self.pipeline.post(self.import_url, body, format="json").status_code == status.HTTP_400_BAD_REQUEST

        assert GenealogySnapshot.objects.count() == 0
        assert ImportRun.objects.count() == 0

    def test_import_without_pipeline_key_then_401_or_403(self):
        anonymous = APIClient()
        assert anonymous.post(self.import_url, DOCUMENT, format="json").status_code == status.HTTP_401_UNAUTHORIZED

        curator = APIClient()
        curator.credentials(HTTP_X_API_KEY=settings.CURATION_API_KEY)
        assert curator.post(self.import_url, DOCUMENT, format="json").status_code == status.HTTP_403_FORBIDDEN

    def test_get_then_latest_document_with_etag(self):
        self.pipeline.post(self.import_url, DOCUMENT, format="json")
        changed = {**DOCUMENT, "traditions": [{**TRADITION, "label": "Delta blues"}]}
        checksum = self.pipeline.post(self.import_url, changed, format="json").json()["checksum"]

        response = APIClient().get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == changed
        assert response["ETag"] == f'"{checksum}"'

    def test_get_with_matching_etag_then_304(self):
        checksum = self.pipeline.post(self.import_url, DOCUMENT, format="json").json()["checksum"]

        response = APIClient().get(self.url, HTTP_IF_NONE_MATCH=f'"{checksum}"')

        assert response.status_code == status.HTTP_304_NOT_MODIFIED
        assert response["ETag"] == f'"{checksum}"'

    def test_get_with_stale_etag_then_200(self):
        self.pipeline.post(self.import_url, DOCUMENT, format="json")

        assert APIClient().get(self.url, HTTP_IF_NONE_MATCH='"stale"').status_code == status.HTTP_200_OK

    def test_get_without_snapshot_then_404(self):
        assert APIClient().get(self.url).status_code == status.HTTP_404_NOT_FOUND

    def test_admin_import_then_snapshot_without_import_run(self):
        response = self.api_client.post(self.import_url, DOCUMENT, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert GenealogySnapshot.objects.get().import_run is None
        assert ImportRun.objects.count() == 0
