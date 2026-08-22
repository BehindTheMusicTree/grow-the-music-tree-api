from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_update_instance_with_genre_removed_then_removed_from_genre_playlists_and_added_to_genreless_playlist(self):
        rock_criteria = self.model_fixture_factory.create_genre(name="Rock")
        punk_criteria = self.model_fixture_factory.create_genre(name="Punk", parent=rock_criteria)
        track = self.model_fixture_factory.create_youtube_track(title="wech", genre=punk_criteria)

        updated_track = YoutubeTrack.objects.update_instance(track, genre=None)

        assert updated_track.genre is None

        assert not TrackPlaylistRel.objects.filter(playlist=rock_criteria.criteria_playlist, track=track).exists()
        assert not TrackPlaylistRel.objects.filter(playlist=punk_criteria.criteria_playlist, track=track).exists()

        genreless_playlist = GenrePlaylist.objects.get(user=self.system_user, criteria=None)
        tracks_dict_by_position = genreless_playlist.tracks_not_archived_dict_by_position
        assert len(tracks_dict_by_position) == 1
        assert tracks_dict_by_position[1].uuid == track.uuid
