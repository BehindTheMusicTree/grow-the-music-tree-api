from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status

from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    list_endpoint = "song-list"

    def test_list_returns_created_tracks(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        song = self.model_fixture_factory.create_song(title="Mine", genre=genre, youtube_video_id="abc123defgh")

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["overallTotal"] == 1
        assert response.data["results"][0]["uuid"] == str(song.uuid)

    def test_list_does_not_return_other_users_tracks(self):
        other_user = User.objects.create(username="other-user")
        other_genre = self.model_fixture_factory.create_genre("Jazz", user=other_user)
        self.model_fixture_factory.create_song(
            title="Not Mine", genre=other_genre, user=other_user, youtube_video_id="def456ghijk"
        )

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["overallTotal"] == 0

    def test_list_includes_youtube_video_id(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_song(title="Track Title", genre=genre, youtube_video_id="abc123defgh")

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.data["results"][0]["youtube_video_id"] == "abc123defgh"

    def test_list_includes_musicbrainz_recording_id(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_song(
            title="Track Title", genre=genre, musicbrainz_recording_id="b1a9c0e9-d987-4042-ae91-78d6a3267d69"
        )

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.data["results"][0]["musicbrainz_recording_id"] == "b1a9c0e9-d987-4042-ae91-78d6a3267d69"

    def test_list_includes_null_youtube_unplayable_reason_for_playable_track(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_song(title="Track Title", genre=genre)

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.json()["results"][0]["youtubeUnplayableReason"] is None

    def test_list_includes_song_without_video_with_null_youtube_video(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_song(title="No video", genre=genre, youtube_video_id=None)

        response = self.api_client.get(path=reverse(self.list_endpoint))

        [song] = response.json()["results"]
        assert song["youtubeVideo"] is None

    def test_list_nests_youtube_video(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_song(title="Track Title", genre=genre, youtube_video_id="abc123defgh")

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.json()["results"][0]["youtubeVideo"] == {
            "id": "abc123defgh",
            "unplayableReason": None,
            "viewCount": None,
        }

    def test_list_exposes_youtube_view_count(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_song(
            title="Track Title", genre=genre, youtube_video_id="abc123defgh", youtube_view_count=1241
        )

        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.json()["results"][0]["youtubeVideo"]["viewCount"] == 1241

    def test_genre_filter_covers_descendants_and_excludes_siblings(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        punk = self.model_fixture_factory.create_genre("Punk", parent=rock)
        jazz = self.model_fixture_factory.create_genre("Jazz")
        own = self.model_fixture_factory.create_song(title="Own", genre=rock)
        child = self.model_fixture_factory.create_song(title="Child", genre=punk)
        self.model_fixture_factory.create_song(title="Sibling", genre=jazz)

        response = self.api_client.get(path=reverse(self.list_endpoint), data={"genre": str(rock.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert {r["uuid"] for r in response.data["results"]} == {str(own.uuid), str(child.uuid)}

    def test_list_cursor_walks_subtree_once_across_genres(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        blues_rock = self.model_fixture_factory.create_genre("Blues rock", parent=rock)
        expected = set()
        for genre in (rock, blues_rock):
            for index in range(3):
                song = self.model_fixture_factory.create_song(title=f"{genre.name}{index}", genre=genre)
                expected.add(str(song.uuid))
        self.model_fixture_factory.create_song(title="Other", genre=self.model_fixture_factory.create_genre("Jazz"))
        path = reverse(self.list_endpoint)

        seen = []
        response = self.api_client.get(path=path, data={"genre": str(rock.uuid), "pageSize": 2, "withTotal": "false"})
        while True:
            assert response.status_code == status.HTTP_200_OK, response.content
            assert response.data["page"] is None
            seen += [r["uuid"] for r in response.data["results"]]
            if response.data["next"] is None:
                break
            response = self.api_client.get(response.data["next"])

        assert len(seen) == len(expected)
        assert set(seen) == expected

    def test_list_cursor_requires_genre(self):
        response = self.api_client.get(path=reverse(self.list_endpoint), data={"withTotal": "false"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_cursor_rejects_ordering(self):
        genre = self.model_fixture_factory.create_genre("Rock")

        response = self.api_client.get(
            path=reverse(self.list_endpoint),
            data={"genre": str(genre.uuid), "withTotal": "false", "ordering": "title"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_invalid_cursor_is_rejected(self):
        genre = self.model_fixture_factory.create_genre("Rock")

        response = self.api_client.get(
            path=reverse(self.list_endpoint),
            data={"genre": str(genre.uuid), "withTotal": "false", "cursor": "not-a-cursor"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_without_total_skips_count_and_pages_by_next_link(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        for index in range(3):
            self.model_fixture_factory.create_song(
                title=f"T{index}", genre=genre, youtube_video_id=f"abc123def{index}x"
            )
        path = reverse(self.list_endpoint)

        first = self.api_client.get(path=path, data={"genre": str(genre.uuid), "pageSize": 2, "withTotal": "false"})
        second = self.api_client.get(
            path=path, data={"genre": str(genre.uuid), "pageSize": 2, "page": 2, "withTotal": "false"}
        )

        assert first.status_code == status.HTTP_200_OK, first.content
        assert first.data["overallTotal"] is None
        assert len(first.data["results"]) == 2
        assert first.data["next"] is not None
        assert len(second.data["results"]) == 1
        assert second.data["next"] is None
        assert second.data["previous"] is not None
