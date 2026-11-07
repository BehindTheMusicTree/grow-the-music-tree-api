from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_tracks_page_is_position_ordered_without_nested_playlists(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_song(title="First", genre=rock_criteria)
        second = self.model_fixture_factory.create_song(title="Second", genre=rock_criteria)
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
        self.model_fixture_factory.create_song(title="Track Title", genre=rock_criteria, youtube_video_id="abc123defgh")
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["track"]["youtubeVideoId"] == "abc123defgh"

    def test_tracks_page_nests_youtube_video_and_skips_unplayable(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_song(title="Track Title", genre=rock_criteria, youtube_video_id="abc123defgh")
        self.model_fixture_factory.create_song(title="No video", genre=rock_criteria, youtube_video_id=None)
        self.model_fixture_factory.create_song(
            title="Private", genre=rock_criteria, youtube_video_id="zzz123defgh", youtube_unplayable_reason="private"
        )
        playlist = GenrePlaylist.objects.get(criteria=rock_criteria)

        response = self.api_client.get(path=reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid}))

        [rel] = response.json()["results"]
        assert rel["track"]["youtubeVideo"] == {
            "id": "abc123defgh",
            "unplayableReason": None,
            "viewCount": None,
            "availability": {"status": "unknown", "reason": None, "country": None},
        }

    def test_tracks_from_starts_at_given_track_404s_on_absent_and_400s_on_non_uuid(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        for title in ("A", "B", "C"):
            self.model_fixture_factory.create_song(title=title, genre=rock_criteria)
        jazz_track = self.model_fixture_factory.create_song(
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

    @override_settings(VIEWER_CONTEXT_TOKEN="trusted")
    def test_country_filter_precedes_pagination_and_anchor_without_changing_membership(self):
        genre = self.model_fixture_factory.create_genre(name="regional")
        first = self.model_fixture_factory.create_song(title="First", genre=genre)
        blocked = self.model_fixture_factory.create_song(title="Blocked", genre=genre)
        blocked.youtube_region_restriction = {"mode": "allowed", "countries": ["FR"]}
        blocked.save(update_fields=["youtube_region_restriction"])
        playlist = GenrePlaylist.objects.get(criteria=genre)
        path = reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid})
        headers = {"HTTP_X_VIEWER_CONTEXT_TOKEN": "trusted", "HTTP_X_VIEWER_COUNTRY": "AL"}
        response = self.api_client.get(path, {"page_size": 1}, **headers)
        assert response.status_code == 200
        assert response.json()["overallTotal"] == 1
        assert response.json()["results"][0]["track"]["uuid"] == str(first.uuid)
        assert response.json()["results"][0]["track"]["youtubeVideo"]["availability"]["country"] == "AL"
        assert response["Cache-Control"] == "private, no-store"
        assert self.api_client.get(path, {"from": str(blocked.uuid)}, **headers).status_code == 404
        assert (
            self.api_client.get(path, HTTP_X_VIEWER_CONTEXT_TOKEN="trusted", HTTP_X_VIEWER_COUNTRY="FR").json()[
                "overallTotal"
            ]
            == 2
        )
        playlist.refresh_from_db()
        assert playlist.tracks_count == 2

    def test_coverage_and_artist_filter_before_anchor(self):
        factory = self.model_fixture_factory
        rock = factory.create_genre("Rock")
        child = factory.create_genre("Punk", parent=rock)
        artist = factory.create_artist("Band")
        other = factory.create_artist("Other")
        direct = factory.create_song(title="Direct", genre=rock, artists=[artist])
        descendant = factory.create_song(title="Child", genre=child, artists=[artist])
        factory.create_song(title="Other", genre=rock, artists=[other])
        path = reverse("genre-playlist-tracks", kwargs={"pk": GenrePlaylist.objects.get(criteria=rock).uuid})
        params = {"coverage": "genre_only", "artist": str(artist.uuid)}
        response = self.api_client.get(path, params)
        assert response.status_code == 200
        assert [row["track"]["uuid"] for row in response.json()["results"]] == [str(direct.uuid)]
        assert self.api_client.get(path, {**params, "from": str(descendant.uuid)}).status_code == 404
        inclusive = self.api_client.get(path, {**params, "coverage": "genre_and_subgenres"})
        assert {row["track"]["uuid"] for row in inclusive.json()["results"]} == {str(direct.uuid), str(descendant.uuid)}
        assert self.api_client.get(path, {"coverage": "invalid"}).status_code == 400
        assert self.api_client.get(path, {"artist": "invalid"}).status_code == 400

    def test_genreless_playlist_is_exact_and_rejects_coverage_parameters(self):
        factory = self.model_fixture_factory
        genreless = factory.create_song(title="Genreless", genre=None)
        factory.create_song(title="Genre", genre=factory.create_genre("Jazz"))
        playlist = GenrePlaylist.objects.get(user__isnull=True, criteria__isnull=True)
        path = reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid})
        response = self.api_client.get(path)
        assert response.status_code == 200
        assert [row["track"]["uuid"] for row in response.json()["results"]] == [str(genreless.uuid)]
        for params in ({"coverage": "genre_only"}, {"coverage": "genre_and_subgenres"}, {"subgenres": "all"}):
            assert self.api_client.get(path, params).status_code == 400

    def test_subgenre_scopes_filter_real_members_before_anchor(self):
        factory = self.model_fixture_factory
        parent = factory.create_genre("Canonical")
        child = factory.create_genre("Canonical child", parent=parent)
        regional = factory.create_genre("Regional child", tree_name="regional")
        regional.additional_primary_parents.add(parent)
        direct = factory.create_song("Direct", genre=parent)
        canonical_song = factory.create_song("Canonical song", genre=child)
        regional_song = factory.create_song("Regional song", genre=regional)
        playlist = GenrePlaylist.objects.get(criteria=parent)
        TrackPlaylistRel.objects.get_or_create(playlist=playlist, track=regional_song, defaults={"user": None})
        path = reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid})

        def tracks(**params):
            response = self.api_client.get(path, params)
            assert response.status_code == 200
            return {row["track"]["uuid"] for row in response.json()["results"]}

        assert tracks() == {str(direct.uuid), str(canonical_song.uuid)}
        assert tracks(subgenres="regional") == {str(direct.uuid), str(regional_song.uuid)}
        assert tracks(subgenres="all") == {str(direct.uuid), str(canonical_song.uuid), str(regional_song.uuid)}
        assert self.api_client.get(path, {"from": str(regional_song.uuid)}).status_code == 404
        assert self.api_client.get(path, {"coverage": "genre_only", "subgenres": "all"}).status_code == 400

    def test_regional_playlist_defaults_to_all_and_rejects_other_inclusive_scopes(self):
        factory = self.model_fixture_factory
        regional = factory.create_genre("Regional root", tree_name="regional")
        child = factory.create_genre("Regional descendant", tree_name="regional", parent=regional)
        direct = factory.create_song("Direct", genre=regional)
        descendant = factory.create_song("Descendant", genre=child)
        playlist = GenrePlaylist.objects.get(criteria=regional)
        path = reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid})

        for params in ({}, {"subgenres": "all"}):
            response = self.api_client.get(path, params)
            assert response.status_code == 200
            assert {row["track"]["uuid"] for row in response.json()["results"]} == {
                str(direct.uuid),
                str(descendant.uuid),
            }
        for scope in ("canonical", "regional"):
            assert self.api_client.get(path, {"subgenres": scope}).status_code == 400
