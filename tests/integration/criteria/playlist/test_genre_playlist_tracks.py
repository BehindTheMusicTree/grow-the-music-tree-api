from django.urls import reverse
from rest_framework import status

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_tracks_page_is_position_ordered_without_nested_playlists(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_recording(title="First", genre=rock_criteria)
        second = self.model_fixture_factory.create_recording(title="Second", genre=rock_criteria)
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(
            path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}), data={"page_size": 1}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["overallTotal"] == 2
        [rel] = body["results"]
        assert rel["position"] == 1
        assert rel["track"]["uuid"] == str(second.uuid)
        assert "playlists" not in rel["track"]

    def test_tracks_page_returns_track_youtube_video_id(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_recording(
            title="Track Title", genre=rock_criteria, youtube_video_id="abc123defgh"
        )
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["track"]["youtubeVideoId"] == "abc123defgh"

    def test_tracks_page_nests_youtube_video_and_skips_unplayable(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_recording(
            title="Track Title", genre=rock_criteria, youtube_video_id="abc123defgh"
        )
        self.model_fixture_factory.create_recording(title="No video", genre=rock_criteria, youtube_video_id=None)
        self.model_fixture_factory.create_recording(
            title="Private", genre=rock_criteria, youtube_video_id="zzz123defgh", youtube_unplayable_reason="private"
        )
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}))

        [rel] = response.json()["results"]
        assert rel["track"]["youtubeVideo"] == {"id": "abc123defgh", "unplayableReason": None}

    def test_tracks_from_starts_at_given_track_404s_on_absent_and_400s_on_non_uuid(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        for title in ("A", "B", "C"):
            self.model_fixture_factory.create_recording(title=title, genre=rock_criteria)
        jazz_track = self.model_fixture_factory.create_recording(
            title="Elsewhere", genre=self.model_fixture_factory.create_genre(name="jazz")
        )
        path = reverse("genre-playlist-tracks", kwargs={"pk": GenrePlaylist.objects.get(criteria=rock_criteria).uuid})
        full_order = [rel["track"]["uuid"] for rel in self.api_client.get(path=path).json()["results"]]

        response = self.api_client.get(path=path, data={"from": full_order[1]})

        assert response.status_code == status.HTTP_200_OK
        assert [rel["track"]["uuid"] for rel in response.json()["results"]] == full_order[1:]
        assert response.json()["overallTotal"] == 2
        assert self.api_client.get(path=path, data={"from": str(jazz_track.uuid)}).status_code == (
            status.HTTP_404_NOT_FOUND
        )
        assert self.api_client.get(path=path, data={"from": "nope"}).status_code == status.HTTP_400_BAD_REQUEST
