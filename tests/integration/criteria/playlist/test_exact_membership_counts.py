from django.contrib.auth.models import User
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.genre_music.artist import playlist_counts
from grow.genre_music.membership import exact_membership_counts
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.AppTestCase import AppTestCase


class TestExactMembershipCounts(AppTestCase):
    def test_scoped_projection_counts_only_members_of_the_selected_playlist(self):
        factory = self.model_fixture_factory
        root = factory.create_genre("Root")
        left = factory.create_genre("Left", parent=root)
        right = factory.create_genre("Right", parent=root)
        shared = factory.create_genre("Shared", parent=left)
        shared.additional_primary_parents.add(right)
        regional = factory.create_genre("Regional", tree_name="regional")
        regional.additional_primary_parents.add(root)
        artist = factory.create_artist("Artist")
        other = factory.create_artist("Other")
        direct = factory.create_song("Direct", genre=root, artists=[artist])
        shared_song = factory.create_song("Shared song", genre=shared, artists=[artist])
        regional_song = factory.create_song("Regional song", genre=regional, artists=[artist])
        other_song = factory.create_song("Other song", genre=left, artists=[other])
        playlist = GenrePlaylist.objects.get(criteria=root)
        TrackPlaylistRel.objects.get_or_create(playlist=playlist, track=regional_song, defaults={"user": None})
        TrackPlaylistRel.objects.filter(playlist=playlist, track=other_song).delete()

        # The expected sets are independent of the projection and its graph traversal.
        expected = {
            "canonical": {direct.pk, shared_song.pk},
            "regional": {direct.pk, regional_song.pk},
            "all": {direct.pk, shared_song.pk, regional_song.pk},
        }
        for artist_id in (None, artist.pk):
            counts = playlist_counts(artist_id)[playlist.uuid]
            assert counts.genre_only_tracks_count == 1
            assert counts.genre_and_subgenres_tracks_count == {scope: len(songs) for scope, songs in expected.items()}

        TrackPlaylistRel.objects.filter(playlist=playlist, track=shared_song).delete()
        counts = playlist_counts(None)[playlist.uuid]
        assert counts.genre_and_subgenres_tracks_count == {"canonical": 1, "regional": 2, "all": 2}
        assert TrackPlaylistRel.objects.filter(playlist__criteria_playlist__criteria=shared, track=shared_song).exists()

    def test_global_projection_uses_each_playlists_actual_members(self):
        parent = self.model_fixture_factory.create_genre("Parent")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        song = self.model_fixture_factory.create_song(title="Child song", genre=child)
        parent_playlist = GenrePlaylist.objects.get(criteria=parent)
        child_playlist = GenrePlaylist.objects.get(criteria=child)

        assert playlist_counts(None)[parent_playlist.uuid].default_count == 1
        TrackPlaylistRel.objects.filter(track=song, playlist=parent_playlist).delete()
        counts = playlist_counts(None)
        assert counts.get(parent_playlist.uuid) is None
        assert counts[child_playlist.uuid].default_count == 1

    def test_counts_membership_for_exact_genre_including_genreless(self):
        parent = self.model_fixture_factory.create_genre("Parent")
        child = self.model_fixture_factory.create_genre("Child", parent=parent)
        song = self.model_fixture_factory.create_song(title="Child song", genre=child)
        self.model_fixture_factory.create_song(title="No video", genre=child, youtube_video_id=None)
        self.model_fixture_factory.create_song(title="Genreless", genre=None)
        parent_playlist = GenrePlaylist.objects.get(criteria=parent)
        child_playlist = GenrePlaylist.objects.get(criteria=child)
        genreless = GenrePlaylist.objects.get(criteria__isnull=True)

        counts = exact_membership_counts()
        assert counts.get(parent_playlist.pk, 0) == 0
        assert counts[child_playlist.pk] == 1
        assert counts[genreless.pk] == 1

        TrackPlaylistRel.objects.filter(track=song, playlist=child_playlist).update(position=None)
        assert exact_membership_counts()[child_playlist.pk] == 1
        TrackPlaylistRel.objects.filter(track=song, playlist=child_playlist).delete()
        assert exact_membership_counts().get(child_playlist.pk, 0) == 0

    def test_excludes_membership_with_a_different_owner(self):
        genre = self.model_fixture_factory.create_genre("Jazz")
        song = self.model_fixture_factory.create_song(title="Song", genre=genre)
        playlist = GenrePlaylist.objects.get(criteria=genre)
        relation = TrackPlaylistRel.objects.get(track=song, playlist=playlist)
        other_user = User.objects.create(username="other")

        TrackPlaylistRel.objects.filter(pk=relation.pk).update(user=other_user)
        assert exact_membership_counts().get(playlist.pk, 0) == 0
