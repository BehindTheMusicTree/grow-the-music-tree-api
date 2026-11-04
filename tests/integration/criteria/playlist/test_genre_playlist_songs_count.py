from io import StringIO

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.playlist.CriterialessPlaylistNames import CriterialessPlaylistNames

from grow.model.artist.Artist import Artist
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.Song import Song
from grow.track.direct_songs_count import recount_direct_songs_count
from tests.utils.AppTestCase import AppTestCase

TREE_PATH = reverse("genre-playlist-list") + "tree/"


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.factory = self.model_fixture_factory
        self.rock = self.factory.create_genre("Rock")
        self.punk = self.factory.create_genre("Punk", parent=self.rock)
        self.jazz = self.factory.create_genre("Jazz")

    def stored(self) -> dict[str, int]:
        return {
            name or CriterialessPlaylistNames.GENRE: count
            for name, count in GenrePlaylist.objects.filter(user__isnull=True).values_list(
                "criteria___name", "direct_songs_count"
            )
        }

    def assert_exact(self):
        stored = self.stored()
        recount_direct_songs_count(Song, GenrePlaylist)
        assert stored == self.stored()

    def tree_songs_counts(self) -> dict[str, tuple[int, int]]:
        response = self.api_client.get(TREE_PATH, {"tree_name": "canonical"})
        assert response.status_code == status.HTTP_200_OK
        return {row["name"]: (row["songsCount"], row["tracksCount"]) for row in response.json()}

    def test_tree_folds_playable_and_unplayable_songs_into_ascendants(self):
        self.factory.create_song(title="Playable", genre=self.punk)
        self.factory.create_song(title="No video", genre=self.punk, youtube_video_id=None)
        self.factory.create_song(title="Removed", genre=self.rock, youtube_unplayable_reason="removed")

        counts = self.tree_songs_counts()

        assert counts["Punk"] == (2, 1)
        assert counts["Rock"] == (3, 1)
        assert counts["Jazz"] == (0, 0)
        self.assert_exact()

    def test_genreless_songs_count_on_the_genreless_playlist(self):
        self.factory.create_song(title="Nameless", genre=None)

        assert self.tree_songs_counts()[CriterialessPlaylistNames.GENRE][0] == 1
        self.assert_exact()

    def test_reparenting_moves_the_subtree_count(self):
        self.factory.create_song(title="Punk song", genre=self.punk)

        Genre.objects.update_instance(self.punk, parent=self.jazz)

        assert self.tree_songs_counts()["Rock"][0] == 0
        assert self.tree_songs_counts()["Jazz"][0] == 1
        self.assert_exact()

    def test_count_change_bumps_the_tree_etag(self):
        etag = self.api_client.get(TREE_PATH, {"tree_name": "canonical"})["ETag"]

        self.factory.create_song(title="Song", genre=self.jazz)

        assert self.api_client.get(TREE_PATH, {"tree_name": "canonical"}, HTTP_IF_NONE_MATCH=etag).status_code == 200

    def test_other_owner_songs_are_not_counted(self):
        self.factory.create_song(title="Private", genre=self.jazz, user=User.objects.create(username="other-user"))

        assert self.stored()["Jazz"] == 0

    def test_create_assign_genre_and_delete_keep_counts_exact(self):
        song = self.factory.create_song(title="Song", genre=self.punk)
        assert self.stored()["Punk"] == 1
        self.assert_exact()

        Song.objects.update_instance(song, genre=self.jazz)
        assert (self.stored()["Punk"], self.stored()["Jazz"]) == (0, 1)
        self.assert_exact()

        Song.objects.update_instance(song, genre=None)
        assert self.stored()[CriterialessPlaylistNames.GENRE] == 1
        self.assert_exact()

        Song.objects.delete_instance(song)
        assert self.stored()[CriterialessPlaylistNames.GENRE] == 0
        self.assert_exact()

    def test_unplayable_song_counts_and_playability_change_leaves_count_alone(self):
        song = self.factory.create_song(title="Song", genre=self.jazz, youtube_video_id=None)
        assert self.stored()["Jazz"] == 1

        Song.objects.update_instance(song, youtube_video_id="dQw4w9WgXcQ")

        assert self.stored()["Jazz"] == 1
        self.assert_exact()

    def test_album_delete_decrements_its_songs(self):
        album = self.factory.create_album("Album")
        self.factory.create_song(title="One", genre=self.punk, album=album)
        self.factory.create_song(title="Two", genre=self.jazz, album=album)

        type(album).objects.delete_instance(album)

        assert self.stored()["Punk"] == self.stored()["Jazz"] == 0
        self.assert_exact()

    def test_artist_delete_decrements_its_songs(self):
        artist = self.factory.create_artist("Band")
        self.factory.create_song(title="One", genre=self.punk, artists=[artist])

        Artist.objects.delete_instance(artist)

        assert self.stored()["Punk"] == 0
        self.assert_exact()

    def test_genre_delete_moves_its_songs_to_the_parent(self):
        self.factory.create_song(title="Punk song", genre=self.punk)

        Genre.objects.delete_instance(self.punk)

        assert self.stored()["Rock"] == 1
        self.assert_exact()

    def test_root_genre_delete_moves_its_songs_to_genreless(self):
        self.factory.create_song(title="Jazz song", genre=self.jazz)

        Genre.objects.delete_instance(self.jazz)

        assert self.stored()[CriterialessPlaylistNames.GENRE] == 1
        self.assert_exact()

    def test_recount_command_repairs_a_drifted_count(self):
        self.factory.create_song(title="Punk song", genre=self.punk)
        GenrePlaylist.objects.filter(criteria=self.punk).update(direct_songs_count=0)
        call_command("recount_direct_songs_count", stdout=StringIO())
        assert self.stored()["Punk"] == 1
