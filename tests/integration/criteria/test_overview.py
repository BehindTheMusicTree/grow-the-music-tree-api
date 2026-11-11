import uuid

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide

from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def _get_overview(self, pk, basename="genre"):
        return self.api_client.get(path=reverse(f"{basename}-detail", kwargs={"pk": pk}) + "overview/")

    def _add_essential_songs(self, genre, count):
        for index in range(count):
            track = self.model_fixture_factory.create_song(f"Track {index}", genre=genre)
            track.artists.add(
                self.model_fixture_factory.create_artist(f"Artist {index}a"),
                self.model_fixture_factory.create_artist(f"Artist {index}b"),
            )
            genre.essential_songs.add(track)

    def test_returns_exactly_the_overview_fields_publicly(self):
        root = self.model_fixture_factory.create_genre("Electronic")
        genre = self.model_fixture_factory.create_genre("EDM", parent=root, side=CriteriaSide.POP, summary="Loud.")
        self._add_essential_songs(genre, 1)
        self.api_client.credentials()

        response = self._get_overview(genre.uuid)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert set(body) == {
            "uuid",
            "name",
            "summary",
            "description",
            "summarySourceUrl",
            "side",
            "image",
            "essentialSongs",
        }
        assert body["name"] == "EDM"
        assert body["summary"] == "Loud."
        assert body["side"] == CriteriaSide.POP
        assert [track["title"] for track in body["essentialSongs"]] == ["Track 0"]
        assert set(body["essentialSongs"][0]) == {"uuid", "title", "artists", "rating", "language", "playCount"}
        assert "essentialTracks" not in body

    def test_returns_description_and_summary_source_url(self):
        genre = self.model_fixture_factory.create_genre(
            "EDM", description="Dance music", summary_source_url="https://en.wikipedia.org/wiki/EDM"
        )

        body = self._get_overview(genre.uuid).json()

        assert body["description"] == "Dance music"
        assert body["summarySourceUrl"] == "https://en.wikipedia.org/wiki/EDM"

    def test_returns_the_genre_image_with_its_attribution(self):
        genre = self.model_fixture_factory.create_genre(
            "EDM",
            image_url="https://upload.wikimedia.org/edm.jpg",
            image_page_url="https://commons.wikimedia.org/wiki/File:Edm.jpg",
            image_author="Jane",
            image_license="CC BY-SA 4.0",
            image_license_url="https://creativecommons.org/licenses/by-sa/4.0",
        )

        body = self._get_overview(genre.uuid).json()

        assert body["image"] == {
            "url": "https://upload.wikimedia.org/edm.jpg",
            "pageUrl": "https://commons.wikimedia.org/wiki/File:Edm.jpg",
            "author": "Jane",
            "license": "CC BY-SA 4.0",
            "licenseUrl": "https://creativecommons.org/licenses/by-sa/4.0",
        }

    def test_image_is_null_without_an_image(self):
        genre = self.model_fixture_factory.create_genre("EDM")

        assert self._get_overview(genre.uuid).json()["image"] is None

    def test_tag_overview_has_no_side_or_essential_songs(self):
        tag = self.model_fixture_factory.create_tag("Live")

        response = self._get_overview(tag.uuid, basename="tag")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["side"] is None
        assert response.json()["essentialSongs"] == []
        assert response.json()["description"] is None
        assert response.json()["summarySourceUrl"] is None

    def test_unknown_uuid_returns_404(self):
        response = self._get_overview(uuid.uuid4())

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_query_count_is_constant_in_essential_songs(self):
        few = self.model_fixture_factory.create_genre("Electronic")
        many = self.model_fixture_factory.create_genre("Rock")
        self._add_essential_songs(few, 1)
        self._add_essential_songs(many, 8)

        with CaptureQueriesContext(connection) as few_queries:
            self._get_overview(few.uuid)
        with CaptureQueriesContext(connection) as many_queries:
            response = self._get_overview(many.uuid)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["essentialSongs"]) == 8
        assert len(many_queries.captured_queries) == len(few_queries.captured_queries)
