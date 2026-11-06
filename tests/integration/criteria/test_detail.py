from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCriteriaDetail(GenreTestCase):
    def test_detail_queries_and_fields(self):
        root = self.model_fixture_factory.create_genre("Root")
        small = self.model_fixture_factory.create_genre("Small", parent=root)
        parent = self.model_fixture_factory.create_genre("Parent", parent=root)
        large = self.model_fixture_factory.create_genre("Large", parent=parent)
        self.model_fixture_factory.create_genre("Small child", parent=small)
        for index in range(4):
            child = self.model_fixture_factory.create_genre(f"Child {index}", parent=large)
            self.model_fixture_factory.create_genre(f"Grandchild {index}", parent=child)
        for genre, count in ((small, 1), (large, 4)):
            for index in range(count):
                song = self.model_fixture_factory.create_song(f"{genre.name} {index}", genre=genre)
                song.artists.add(self.model_fixture_factory.create_artist(f"{genre.name} artist {index}"))
                genre.essential_songs.add(song)

        def get(genre):
            return self.api_client.get(reverse("genre-detail", kwargs={"pk": genre.uuid}))

        with CaptureQueriesContext(connection) as small_queries:
            small_response = get(small)
        with CaptureQueriesContext(connection) as large_queries:
            response = get(large)
        assert small_response.status_code == response.status_code == 200
        assert len(small_queries) == len(large_queries)
        body = response.json()
        assert "tracks" not in body and "descendants" not in body
        assert body["tracksCount"] == 4
        assert {rel["ascendant"]["name"] for rel in body["ascendants"]} == {"Root", "Parent"}
        assert {child["name"] for child in body["children"]} == {f"Child {index}" for index in range(4)}
        assert len(body["essentialSongs"]) == 4

    def test_tag_detail(self):
        tag = self.model_fixture_factory.create_tag("Live")
        response = self.api_client.get(reverse("tag-detail", kwargs={"pk": tag.uuid}))
        assert response.status_code == 200
        assert response.json()["essentialSongs"] == []
        assert response.json()["tracksCount"] == 0
        assert "tracks" not in response.json() and "descendants" not in response.json()

    def test_update_and_exclude_queries_do_not_depend_on_song_count(self):
        small = self.model_fixture_factory.create_genre("Small")
        large = self.model_fixture_factory.create_genre("Large")
        for genre, count in ((small, 1), (large, 4)):
            for index in range(count):
                song = self.model_fixture_factory.create_song(f"{genre.name} {index}", genre=genre)
                song.artists.add(self.model_fixture_factory.create_artist(f"{genre.name} artist {index}"))
                genre.essential_songs.add(song)
        with CaptureQueriesContext(connection) as small_queries:
            small_response = self._put_genre(small.uuid, {"summary": "Updated"})
        with CaptureQueriesContext(connection) as large_queries:
            large_response = self._put_genre(large.uuid, {"summary": "Updated"})
        assert small_response.status_code == large_response.status_code == 200
        assert len(small_queries) == len(large_queries)
        with CaptureQueriesContext(connection) as small_queries:
            small_response = self._post_genre_exclude(small.uuid)
        with CaptureQueriesContext(connection) as large_queries:
            large_response = self._post_genre_exclude(large.uuid)
        assert small_response.status_code == large_response.status_code == 200
        assert len(small_queries) == len(large_queries)
