from django.test import override_settings
from django.urls import reverse
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.playable import PLAYABLE
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase

POLICIES = (
    None,
    {"mode": "unrestricted", "countries": []},
    {"mode": "allowed", "countries": ["FR"]},
    {"mode": "allowed", "countries": ["AL"]},
    {"mode": "blocked", "countries": ["FR"]},
    {"mode": "blocked", "countries": ["AL"]},
)


def _unplayable_members():
    return TrackPlaylistRel.objects.filter(
        playlist__criteria_playlist__criteria__isnull=False, track__in=Song.objects.exclude(PLAYABLE)
    )


class TestCase(AppTestCase):
    def test_no_genre_playlist_member_is_unplayable_after_each_writer(self):
        genre = self.model_fixture_factory.create_genre(name="rock")
        self.model_fixture_factory.create_song(title="No video", genre=genre, youtube_video_id=None)
        self.model_fixture_factory.create_song(
            title="Private", genre=genre, youtube_video_id="zzz123defgh", youtube_unplayable_reason="private"
        )
        song = self.model_fixture_factory.create_song(title="Playable", genre=genre)
        assert not _unplayable_members().exists()
        assert TrackPlaylistRel.objects.filter(track=song).exists()

        Song.objects.update_instance(song, youtube_unplayable_reason="removed")
        assert not _unplayable_members().exists()
        assert not TrackPlaylistRel.objects.filter(track=song).exists()

    @override_settings(VIEWER_CONTEXT_TOKEN="trusted")
    def test_bucket_count_equals_the_exact_row_count_for_every_selection_and_country(self):
        root = self.model_fixture_factory.create_genre(name="root")
        child = self.model_fixture_factory.create_genre(name="child", parent=root)
        for genre in (root, child):
            for index, policy in enumerate(POLICIES):
                song = self.model_fixture_factory.create_song(title=f"{genre.name}-{index}", genre=genre)
                Song.objects.filter(pk=song.pk).update(youtube_region_restriction=policy)
        playlist = GenrePlaylist.objects.get(criteria=root)
        path = reverse("genre-playlist-tracks", kwargs={"pk": playlist.uuid})

        for params in ({}, {"coverage": "genre_only"}, {"subgenres": "all"}, {"subgenres": "canonical"}):
            for country in (None, "FR", "AL", "US"):
                headers = {"HTTP_X_VIEWER_CONTEXT_TOKEN": "trusted"}
                if country:
                    headers["HTTP_X_VIEWER_COUNTRY"] = country
                body = self.api_client.get(path, {**params, "page_size": 100}, **headers).json()
                # `from` forces the row-level count, which the bucket arithmetic must reproduce.
                exact = self.api_client.get(
                    path, {**params, "page_size": 1, "from": body["results"][0]["track"]["uuid"]}, **headers
                ).json()
                assert body["overallTotal"] == len(body["results"]) == exact["overallTotal"], (params, country)
