from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.playlist.CriterialessPlaylistNames import CriterialessPlaylistNames

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.factory = self.model_fixture_factory
        self.api_client.credentials()
        self.rock = self.factory.create_genre("Rock")
        self.punk = self.factory.create_genre("Punk", parent=self.rock)
        self.hardcore = self.factory.create_genre("Hardcore", parent=self.punk)
        self.jazz = self.factory.create_genre("Jazz")
        self.artist = self.factory.create_artist("Minor Threat")

    def counts(self, artist=None) -> dict[str, tuple[int, int]]:
        response = self.api_client.get(path=reverse("artist-genre-counts", kwargs={"pk": (artist or self.artist).uuid}))
        assert response.status_code == status.HTTP_200_OK
        names = {
            str(pk): name
            for pk, name in GenrePlaylist.objects.filter(
                uuid__in=[row["genre_playlist"] for row in response.data]
            ).values_list("uuid", "criteria___name")
        }
        return {names[str(row["genre_playlist"])]: (row["songs_count"], row["tracks_count"]) for row in response.data}

    def song(self, title, genre, **kwargs):
        return self.factory.create_song(title=title, genre=genre, artists=[self.artist], **kwargs)

    def test_subtree_folds_into_ascendants_only(self):
        self.song("Straight Edge", self.hardcore)
        self.song("Filler", self.punk)

        assert self.counts() == {"Hardcore": (1, 1), "Punk": (2, 2), "Rock": (2, 2)}

    def test_deep_leaf_only_artist_includes_ancestors(self):
        self.song("Straight Edge", self.hardcore)

        assert self.counts() == {"Hardcore": (1, 1), "Punk": (1, 1), "Rock": (1, 1)}

    def test_songs_count_includes_unplayable_but_tracks_count_does_not(self):
        self.song("Playable", self.punk)
        self.song("No video", self.punk, youtube_video_id=None)
        self.song("Unplayable", self.punk, youtube_unplayable_reason="removed")

        assert self.counts() == {"Punk": (3, 1), "Rock": (3, 1)}

    def test_genreless_songs_count_toward_genreless_playlist(self):
        self.song("Orphan", None)
        self.song("Orphan without video", None, youtube_video_id=None)

        playlist = GenrePlaylist.objects.get(criteria__isnull=True, user__isnull=True)
        response = self.api_client.get(path=reverse("artist-genre-counts", kwargs={"pk": self.artist.uuid}))

        assert playlist.name == CriterialessPlaylistNames.GENRE
        assert [(str(r["genre_playlist"]), r["songs_count"], r["tracks_count"]) for r in response.data] == [
            (str(playlist.uuid), 2, 1)
        ]

    def test_other_artists_songs_are_ignored(self):
        other = self.factory.create_artist("Other")
        self.factory.create_song(title="Bebop", genre=self.jazz, artists=[other])
        self.song("Straight Edge", self.hardcore)

        assert set(self.counts()) == {"Hardcore", "Punk", "Rock"}
        assert self.counts(other) == {"Jazz": (1, 1)}

    def test_artist_without_songs_then_empty(self):
        assert self.counts() == {}

    def test_unknown_artist_then_404(self):
        response = self.api_client.get(
            path=reverse("artist-genre-counts", kwargs={"pk": "0c4b2a83-6a5c-4c1d-9f43-3b9d8f0b2e11"})
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_only_canonical_rows_count(self):
        user = User.objects.create(username="other-user")
        private_genre = self.factory.create_genre("Private", user=user)
        self.factory.create_song(title="Mine", genre=private_genre, artists=[self.artist], user=user)
        self.song("Straight Edge", self.hardcore)

        assert set(self.counts()) == {"Hardcore", "Punk", "Rock"}
