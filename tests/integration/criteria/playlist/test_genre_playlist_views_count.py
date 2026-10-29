from django.db.models import Sum
from django.urls import reverse

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase

TREE_PATH = reverse("genre-playlist-list") + "tree/"


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.rock = self.model_fixture_factory.create_genre("Rock")
        self.punk = self.model_fixture_factory.create_genre("Punk", parent=self.rock)

    def _views(self, genre: Genre) -> int:
        return GenrePlaylist.objects.get(criteria=genre).views_count

    def _assert_matches_rels(self):
        for playlist in CriteriaPlaylist.objects.all():
            expected = playlist.track_playlist_rels.aggregate(total=Sum("track__song__youtube_view_count"))["total"]
            assert playlist.views_count == (expected or 0), playlist

    def test_new_playlist_starts_at_zero(self):
        assert self._views(self.rock) == 0

    def test_song_added_counts_its_views_in_its_genre_and_ancestors(self):
        self.model_fixture_factory.create_song(title="A", genre=self.punk, youtube_view_count=40)
        self.model_fixture_factory.create_song(title="B", genre=self.rock, youtube_view_count=2)

        assert self._views(self.punk) == 40
        assert self._views(self.rock) == 42
        self._assert_matches_rels()

    def test_song_without_view_count_adds_nothing(self):
        self.model_fixture_factory.create_song(title="A", genre=self.punk, youtube_view_count=None)

        assert self._views(self.rock) == 0

    def test_view_count_update_moves_every_playlist_holding_the_song(self):
        song = self.model_fixture_factory.create_song(title="A", genre=self.punk, youtube_view_count=40)

        Song.objects.filter(pk=song.pk).update(youtube_view_count=100)
        assert self._views(self.punk) == 100
        assert self._views(self.rock) == 100

        Song.objects.filter(pk=song.pk).update(youtube_view_count=None)
        assert self._views(self.rock) == 0
        self._assert_matches_rels()

    def test_song_deleted_removes_its_views(self):
        song = self.model_fixture_factory.create_song(title="A", genre=self.punk, youtube_view_count=40)
        self.model_fixture_factory.create_song(title="B", genre=self.punk, youtube_view_count=5)

        song.delete()

        assert self._views(self.punk) == 5
        assert self._views(self.rock) == 5
        self._assert_matches_rels()

    def test_song_moved_to_another_genre_moves_its_views(self):
        jazz = self.model_fixture_factory.create_genre("Jazz")
        song = self.model_fixture_factory.create_song(title="A", genre=self.punk, youtube_view_count=40)

        Song.objects.update_instance(song, actor=None, genre=jazz)

        assert self._views(self.punk) == 0
        assert self._views(self.rock) == 0
        assert self._views(jazz) == 40
        self._assert_matches_rels()

    def test_tree_exposes_views_count(self):
        self.model_fixture_factory.create_song(title="A", genre=self.punk, youtube_view_count=40)

        rows = self.api_client.get(TREE_PATH, {"tree_name": "canonical"}).json()
        views = {row["criteria"]["name"]: row["viewsCount"] for row in rows if row["criteria"]}

        assert views == {"Rock": 40, "Punk": 40}
