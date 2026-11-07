import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection, transaction
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria
from grow.search.trigram import fold_query
from tests.utils.AppTestCase import AppTestCase


@pytest.mark.postgres
class TestGenreSearch(AppTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.api_client.credentials()
        self.factory = self.model_fixture_factory

    def genre(self, name: str, **kwargs) -> Genre:
        return self.factory.create_genre(name, user=None, **kwargs)

    def search(self, q: str, **params):
        return self.api_client.get(path=reverse("genre-search"), data={"q": q, **params})

    def names(self, q: str, **params) -> list[str]:
        response = self.search(q, **params)
        assert response.status_code == status.HTTP_200_OK, response.data
        return [item["name"] for item in response.data]

    def test_anonymous_search_then_result_shape(self):
        rock = self.genre("Rock")
        punk = self.genre("Punk rock", parent=rock, wikidata_id="Q3071")

        response = self.search("punk")

        assert response.status_code == status.HTTP_200_OK
        (item,) = response.data
        assert item == {
            "uuid": str(punk.uuid),
            "name": "Punk rock",
            "wikidata_id": "Q3071",
            "tree_name": CriteriaTreeName.CANONICAL,
            "genre_playlist_uuid": str(punk.criteria_playlist.uuid),
            "is_umbrella": False,
            "root": {"uuid": str(rock.uuid), "name": "Rock"},
            "views_count": 0,
        }

    def test_genre_without_wikidata_id_has_null(self):
        self.genre("Local sound")

        (item,) = self.search("local sound").data

        assert item["wikidata_id"] is None

    def test_accent_case_and_typo_insensitive(self):
        self.genre("Musique concrète")

        assert self.names("MUSIQUE CONCRETE") == ["Musique concrète"]
        assert self.names("musique concrete") == ["Musique concrète"]
        assert self.names("musiqe concrete") == ["Musique concrète"]

    def test_exact_then_prefix_then_fuzzy(self):
        self.genre("Post-house")
        self.genre("House")
        self.genre("House music revival")

        assert self.names("house") == ["House", "House music revival", "Post-house"]

    def test_ties_broken_by_views(self):
        quiet = self.genre("Techno A")
        loud = self.genre("Techno B")
        type(loud.criteria_playlist).objects.filter(pk=loud.criteria_playlist.pk).update(views_count=10)

        response = self.search("techno")

        assert [item["uuid"] for item in response.data] == [str(loud.uuid), str(quiet.uuid)]

    def test_tree_name_filter(self):
        self.genre("Jazz")
        self.genre("Jazz in France", tree_name=CriteriaTreeName.REGIONAL)

        assert self.names("jazz", tree_name=CriteriaTreeName.REGIONAL) == ["Jazz in France"]
        assert self.names("jazz", tree_name=CriteriaTreeName.CANONICAL) == ["Jazz"]
        assert sorted(self.names("jazz")) == ["Jazz", "Jazz in France"]

    def test_unaccepted_root_subtree_excluded(self):
        root = self.genre("Drill root", is_unaccepted_root=True)
        self.genre("Drill", parent=root)

        assert self.names("drill") == []

    def test_user_genres_excluded(self):
        self.factory.create_genre("Private shoegaze", user=User.objects.create_user("curator"))

        assert self.names("shoegaze") == []

    def test_limit(self):
        for i in range(5):
            self.genre(f"Trance {i}")

        assert len(self.names("trance", limit=3)) == 3

    def test_invalid_params(self):
        assert self.search("a").status_code == status.HTTP_400_BAD_REQUEST
        assert self.search("rock", limit=26).status_code == status.HTTP_400_BAD_REQUEST
        assert self.search("rock", tree_name="other").status_code == status.HTTP_400_BAD_REQUEST

    def test_rename_invalidates_cached_results(self):
        genre = self.genre("Grunge")
        assert self.names("grunge") == ["Grunge"]

        Genre.objects.filter(pk=genre.pk).update(_name="Seattle sound")

        assert self.names("grunge") == []

    def test_search_uses_trigram_index(self):
        for i in range(200):
            self.genre(f"Filler genre {i}")
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE grow_criteria")
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            folded = fold_query(cursor, "filler")
            plan = Criteria.objects.filter(folded_name__trigram_word_similar=folded).explain()

        assert "grow_criteria_folded_name_trgm" in plan
