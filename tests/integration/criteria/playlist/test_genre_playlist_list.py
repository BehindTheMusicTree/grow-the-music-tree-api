from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_list_genre_playlists_returns_criteria_side(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        self.model_fixture_factory.create_genre("EDM", parent=root, side=CriteriaSide.POP)

        response = self.api_client.get(path=reverse("genre-playlist-list"))

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        edm_result = next(result for result in results if result["criteria"] and result["criteria"]["name"] == "EDM")
        assert edm_result["criteria"]["side"] == CriteriaSide.POP

    def test_list_genre_playlists_returns_criteria_summary(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        self.model_fixture_factory.create_genre("EDM", parent=root, summary="Electronic dance music")

        response = self.api_client.get(path=reverse("genre-playlist-list"))

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        edm_result = next(result for result in results if result["criteria"] and result["criteria"]["name"] == "EDM")
        assert edm_result["criteria"]["summary"] == "Electronic dance music"

    def test_list_genre_playlists_filters_by_tree_scope(self):
        self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_genre("Italian progressive rock", allows_multiple_primary_parents=True)

        response = self.api_client.get(
            path=reverse("genre-playlist-list"), data={"allows_multiple_primary_parents": "false"}
        )

        assert response.status_code == status.HTTP_200_OK
        names = [result["criteria"]["name"] for result in response.json()["results"] if result["criteria"]]
        assert names == ["Rock"]

    def test_list_genre_playlists_returns_304_when_etag_matches(self):
        self.model_fixture_factory.create_genre("Electronic")

        first = self.api_client.get(path=reverse("genre-playlist-list"))
        second = self.api_client.get(path=reverse("genre-playlist-list"), HTTP_IF_NONE_MATCH=first["ETag"])

        assert second.status_code == status.HTTP_304_NOT_MODIFIED
