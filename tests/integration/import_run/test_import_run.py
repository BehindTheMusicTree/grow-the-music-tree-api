from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.import_run.ImportRun import ImportRun
from tests.utils.AppTestCase import AppTestCase

POP = {Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}
CANONICAL_TREE = [POP, {Fields.ID: "Q11399", Fields.NAME_PUBLIC: "Rock", Fields.CHILDREN: []}]
FOLK = {Fields.ID: "Q1342372", Fields.NAME_PUBLIC: "Breton folk", Fields.CHILDREN: []}
REGIONAL_TREE = [
    {Fields.ID: "Q1059", Fields.NAME_PUBLIC: "Music of Brittany", Fields.CHILDREN: [FOLK]},
    {Fields.ID: "Q1060", Fields.NAME_PUBLIC: "Music of France", Fields.CHILDREN: []},
]
SONGS = [
    {
        "title": "Comfortably Numb",
        "artist": "Pink Floyd",
        "youtubeVideoId": "abc123defgh",
        "musicbrainzRecordingId": "b1a9c0e9-d987-4042-ae91-78d6a3267d69",
        "genreName": "Rock",
    },
    {
        "title": "Unmatched",
        "artist": "Nobody",
        "youtubeVideoId": "zzz123defgh",
        "musicbrainzRecordingId": "0c4b2a83-6a5c-4c1d-9f43-3b9d8f0b2e11",
        "genreName": "Unknown",
    },
]


class TestImportRun(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

    def _import_tree(self, client, tree_name: str, tree: list):
        return client.post(
            path=reverse("genre-list") + "tree/import/",
            data={Fields.TREE_NAME: tree_name, Fields.TREE: tree},
            format="json",
        )

    def _import_songs(self, client):
        return client.post(path=reverse("youtube-track-list") + "songs/import/", data=SONGS, format="json")

    def _runs(self) -> list[tuple[str, int, int | None]]:
        return list(ImportRun.objects.order_by("pk").values_list("kind", "count", "skipped_count"))

    def test_pipeline_tree_imports_then_recorded_with_node_count(self):
        assert self._import_tree(self.pipeline, "canonical", CANONICAL_TREE).status_code == status.HTTP_201_CREATED
        assert self._import_tree(self.pipeline, "regional", REGIONAL_TREE).status_code == status.HTTP_201_CREATED

        assert self._runs() == [("canonical_tree", 2, None), ("regional_tree", 3, None)]

    def test_admin_tree_import_then_not_recorded(self):
        assert self._import_tree(self.api_client, "canonical", CANONICAL_TREE).status_code == status.HTTP_201_CREATED

        assert self._runs() == []

    def test_failed_tree_import_then_not_recorded(self):
        response = self._import_tree(self.pipeline, "canonical", CANONICAL_TREE[1:])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._runs() == []

    def test_pipeline_songs_import_then_recorded_with_skipped(self):
        self.model_fixture_factory.create_genre("Rock")

        assert self._import_songs(self.pipeline).status_code == status.HTTP_202_ACCEPTED

        assert self._runs() == [("songs", 1, 1)]

    def test_admin_songs_import_then_not_recorded(self):
        self.model_fixture_factory.create_genre("Rock")

        assert self._import_songs(self.api_client).status_code == status.HTTP_202_ACCEPTED

        assert self._runs() == []

    def test_report_unresolved_genre_tags_then_201(self):
        response = self.pipeline.post(
            path=reverse("import-runs-unresolved-genre-tags"), data={"unresolvedGenreTagCount": 7}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert {k: body[k] for k in ("kind", "count", "skippedCount")} == {
            "kind": "unresolved_genre_tags",
            "count": 7,
            "skippedCount": None,
        }
        assert body["importedOn"]
        assert self._runs() == [("unresolved_genre_tags", 7, None)]

    def test_report_negative_count_then_400(self):
        response = self.pipeline.post(
            path=reverse("import-runs-unresolved-genre-tags"), data={"unresolvedGenreTagCount": -1}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._runs() == []

    def test_report_anonymous_then_401(self):
        response = APIClient().post(
            path=reverse("import-runs-unresolved-genre-tags"), data={"unresolvedGenreTagCount": 1}, format="json"
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_latest_then_newest_run_per_kind(self):
        ImportRun.objects.create(kind=ImportRun.Kind.SONGS, count=1, skipped_count=0)
        ImportRun.objects.create(kind=ImportRun.Kind.SONGS, count=2, skipped_count=3)
        ImportRun.objects.create(kind=ImportRun.Kind.CANONICAL_TREE, count=10)

        response = self.api_client.get(path=reverse("import-runs-latest"))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["regionalTree"] is None and body["unresolvedGenreTags"] is None
        assert (body["songs"]["count"], body["songs"]["skippedCount"]) == (2, 3)
        assert (body["canonicalTree"]["kind"], body["canonicalTree"]["count"]) == ("canonical_tree", 10)

    def test_list_then_newest_first_and_filtered_by_kind(self):
        for count in (1, 2):
            ImportRun.objects.create(kind=ImportRun.Kind.SONGS, count=count, skipped_count=0)
        ImportRun.objects.create(kind=ImportRun.Kind.CANONICAL_TREE, count=3)

        all_runs = self.api_client.get(path=reverse("import-runs")).json()
        songs = self.api_client.get(path=reverse("import-runs"), data={"kind": "songs"}).json()

        assert [r["count"] for r in all_runs["results"]] == [3, 2, 1]
        assert [r["count"] for r in songs["results"]] == [2, 1]

    def test_list_unknown_kind_then_400(self):
        response = self.api_client.get(path=reverse("import-runs"), data={"kind": "nope"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_read_with_pipeline_key_then_403_and_anonymous_then_401(self):
        for name in ("import-runs", "import-runs-latest"):
            assert self.pipeline.get(path=reverse(name)).status_code == status.HTTP_403_FORBIDDEN
            assert APIClient().get(path=reverse(name)).status_code == status.HTTP_401_UNAUTHORIZED
