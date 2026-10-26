import uuid

import pytest
from django.urls import reverse
from rest_framework import status

from grow.model.artist.Artist import SPECIAL_PURPOSE_ARTIST_MBIDS
from tests.utils.AppTestCase import AppTestCase


@pytest.mark.postgres
class TestArtistSearch(AppTestCase):
    def setUp(self):
        super().setUp()
        self.api_client.credentials()
        self.factory = self.model_fixture_factory

    def search(self, q: str, **params):
        return self.api_client.get(path=reverse("artist-search"), data={"q": q, **params})

    def names(self, q: str, **params) -> list[str]:
        response = self.search(q, **params)
        assert response.status_code == status.HTTP_200_OK
        return [item["name"] for item in response.data]

    def test_invalid_bearer_token_is_ignored(self):
        self.factory.create_artist("Nirvana")
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-grow-token")

        response = self.search("nirvana")

        assert response.status_code == status.HTTP_200_OK

    def test_anonymous_search_then_result_shape(self):
        artist = self.factory.create_artist(
            "Nirvana", type="group", country="GB", begin_year=1967, disambiguation="60s UK band", recording_count=3
        )

        response = self.search("nirvana")

        assert response.status_code == status.HTTP_200_OK
        (item,) = response.data
        assert item == {
            "uuid": str(artist.uuid),
            "name": "Nirvana",
            "disambiguation": "60s UK band",
            "type": "group",
            "country": "GB",
            "begin_year": 1967,
            "end_year": None,
            "matched_alias": None,
            "recording_count": 3,
        }

    def test_accent_and_case_insensitive(self):
        self.factory.create_artist("Björk")

        assert self.names("BJORK") == ["Björk"]

    def test_article_dropped_still_matches(self):
        self.factory.create_artist("The Beatles")

        assert self.names("beatles") == ["The Beatles"]

    def test_typo_tolerated(self):
        self.factory.create_artist("Radiohead")

        assert self.names("radiohed") == ["Radiohead"]

    def test_alias_match_sets_matched_alias(self):
        artist = self.factory.create_artist("Андрей Миронов")
        artist.aliases.create(name="Andrei Mironov")

        (item,) = self.search("andrei mironov").data

        assert (item["name"], item["matched_alias"]) == ("Андрей Миронов", "Andrei Mironov")

    def test_name_match_wins_over_weaker_alias_so_no_matched_alias(self):
        artist = self.factory.create_artist("Prince")
        artist.aliases.create(name="Prince Rogers Nelson")

        (item,) = self.search("prince").data

        assert item["matched_alias"] is None

    def test_exact_before_prefix_before_fuzzy(self):
        self.factory.create_artist("Nirvana Tribute Band", recording_count=900)
        self.factory.create_artist("Nirvanas", recording_count=500)
        self.factory.create_artist("Nirvana", recording_count=1)

        assert self.names("nirvana")[0] == "Nirvana"

    def test_recording_count_breaks_ties(self):
        self.factory.create_artist("Genesis", disambiguation="obscure", recording_count=1)
        self.factory.create_artist("Genesis", disambiguation="the band", recording_count=50)

        results = self.search("genesis").data

        assert [r["disambiguation"] for r in results] == ["the band", "obscure"]

    def test_special_purpose_artists_excluded(self):
        for mbid in SPECIAL_PURPOSE_ARTIST_MBIDS:
            self.factory.create_artist("Various Artists", musicbrainz_artist_id=mbid)
        self.factory.create_artist("Various Artists Collective", musicbrainz_artist_id=uuid.uuid4())

        assert self.names("various artists") == ["Various Artists Collective"]

    def test_limit_applied(self):
        for i in range(5):
            self.factory.create_artist(f"Metallica {i}")

        assert len(self.names("metallica", limit=3)) == 3

    def test_limit_above_max_then_400(self):
        assert self.search("metallica", limit=26).status_code == status.HTTP_400_BAD_REQUEST

    def test_short_query_then_400(self):
        assert self.search("a").status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_query_then_400(self):
        response = self.api_client.get(path=reverse("artist-search"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_match_then_empty(self):
        self.factory.create_artist("Radiohead")

        assert self.names("zzzzqqqq") == []
