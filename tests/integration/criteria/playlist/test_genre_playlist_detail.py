from django.urls import reverse
from rest_framework import status

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_retrieve_genre_playlist_returns_tracks_archived_count(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-detail", kwargs={"pk": playlist.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["tracks_archived_count"] == 0

    def test_retrieve_genre_playlist_returns_track_youtube_video_id(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        youtube_track = self.model_fixture_factory.create_youtube_track(
            title="Track Title",
            genre=rock_criteria,
            youtube_video_id="abc123defgh",
        )
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-detail", kwargs={"pk": playlist.uuid}))

        assert response.status_code == status.HTTP_200_OK
        track_playlist_relations = response.json()["track_playlist_relations"]
        assert len(track_playlist_relations) == 1
        assert track_playlist_relations[0]["track"]["uuid"] == str(youtube_track.uuid)
        assert track_playlist_relations[0]["track"]["youtube_video_id"] == youtube_track.youtube_video_id
        assert track_playlist_relations[0]["track"]["youtube_video_id"] == "abc123defgh"
