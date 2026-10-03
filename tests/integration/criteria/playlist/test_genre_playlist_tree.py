import re
from importlib import import_module
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext, override_settings
from django.urls import reverse
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.play.Play import Play
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase

TRACKED_TABLES = set(import_module("grow.migrations.0039_genre_tree_version").TRACKED_TABLES)
TREE_PATH = reverse("genre-playlist-list") + "tree/"
# Read by the tree but deliberately untriggered, with the reason.
UNTRACKED_READS = {"grow_genre_tree_version": "holds the token the triggers bump"}


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.rock = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_genre("Punk", parent=self.rock)
        self.model_fixture_factory.create_genre("Italian progressive rock", tree_name="regional")

    def _assert_bumps(self, write):
        before = GenreTreeVersion.current_token()
        write()
        assert GenreTreeVersion.current_token() != before

    def test_play_leaves_token_unchanged(self):
        # Content types created inside this rolled-back test would otherwise stay cached for later tests.
        self.addCleanup(ContentType.objects.clear_cache)
        playlist = GenrePlaylist.objects.get(criteria=self.rock).playlist
        track = self.model_fixture_factory.create_youtube_track(title="Song", genre=self.rock)
        before = GenreTreeVersion.current_token()

        Play.objects.create(content=playlist)
        Play.objects.create(content=track)

        assert GenreTreeVersion.current_token() == before
        playlist.refresh_from_db()
        assert playlist.play_count == 1

    def test_etag_changes_with_git_commit(self):
        with override_settings(GIT_COMMIT="aaa"):
            first = self.api_client.get(TREE_PATH, {"tree_name": "canonical"})
        with override_settings(GIT_COMMIT="bbb"):
            second = self.api_client.get(TREE_PATH, {"tree_name": "canonical"}, HTTP_IF_NONE_MATCH=first["ETag"])

        assert second.status_code == status.HTTP_200_OK
        assert second["ETag"] != first["ETag"]

    def test_tree_served_uncached_when_redis_down(self):
        down = RedisConnectionError("down")
        with (
            patch("django.core.cache.cache.get", side_effect=down),
            patch("django.core.cache.cache.set", side_effect=down),
            self.assertLogs(level="WARNING"),
        ):
            response = self.api_client.get(TREE_PATH, {"tree_name": "canonical"})

        assert response.status_code == status.HTTP_200_OK
        assert "Rock" in [row["criteria"] and row["criteria"]["name"] for row in response.json()]

    def test_tree_equals_unpaginated_list(self):
        for tree_name in ("canonical", "regional"):
            tree = self.api_client.get(TREE_PATH, {"tree_name": tree_name})
            listed = self.api_client.get(reverse("genre-playlist-list"), {"tree_name": tree_name, "page_size": 1000})

            assert tree.status_code == status.HTTP_200_OK
            assert tree.json() == listed.json()["results"]

    def test_tree_without_valid_tree_name_then_400(self):
        assert self.api_client.get(TREE_PATH).status_code == status.HTTP_400_BAD_REQUEST
        assert self.api_client.get(TREE_PATH, {"tree_name": "bogus"}).status_code == status.HTTP_400_BAD_REQUEST

    def test_tree_returns_304_when_etag_matches(self):
        first = self.api_client.get(TREE_PATH, {"tree_name": "canonical"})
        second = self.api_client.get(TREE_PATH, {"tree_name": "canonical"}, HTTP_IF_NONE_MATCH=first["ETag"])

        assert second.status_code == status.HTTP_304_NOT_MODIFIED
        assert second["ETag"] == first["ETag"]

    def test_tree_reflects_writes_after_cache_fill(self):
        first = self.api_client.get(TREE_PATH, {"tree_name": "canonical"})
        self.model_fixture_factory.create_genre("Jazz")
        second = self.api_client.get(TREE_PATH, {"tree_name": "canonical"}, HTTP_IF_NONE_MATCH=first["ETag"])

        assert second.status_code == status.HTTP_200_OK
        assert "Jazz" in [row["criteria"] and row["criteria"]["name"] for row in second.json()]

    def test_token_bumps_on_queryset_update(self):
        self._assert_bumps(lambda: Genre.objects.filter(pk=self.rock.pk).update(summary="Loud"))

    def test_token_bumps_on_bulk_create(self):
        punk = Genre.objects.get(name="Punk")
        through = Genre.secondary_parents.through
        self._assert_bumps(
            lambda: through.objects.bulk_create([through(from_criteria_id=punk.pk, to_criteria_id=self.rock.pk)])
        )

    def test_token_bumps_on_track_add_and_delete(self):
        track = None

        def add():
            nonlocal track
            track = self.model_fixture_factory.create_youtube_track(title="Song", genre=self.rock)

        self._assert_bumps(add)
        self._assert_bumps(lambda: track.delete())  # noqa: PLW0108 -- track is bound only after add() runs

    def test_token_bumps_on_playlist_update(self):
        self._assert_bumps(
            lambda: GenrePlaylist.objects.filter(criteria=self.rock).update(updated_on=self.rock.updated_on)
        )

    def test_every_table_the_tree_reads_has_a_trigger(self):
        with CaptureQueriesContext(connection) as queries:
            self.api_client.get(TREE_PATH, {"tree_name": "canonical"})
        read = {t for q in queries.captured_queries for t in re.findall(r'(?:FROM|JOIN) "(\w+)"', q["sql"])}

        assert read - UNTRACKED_READS.keys() <= TRACKED_TABLES
        with connection.cursor() as cursor:
            cursor.execute("SELECT tbl_name FROM sqlite_master WHERE type = 'trigger'")
            triggered = {row[0] for row in cursor.fetchall()}
        assert triggered >= TRACKED_TABLES
