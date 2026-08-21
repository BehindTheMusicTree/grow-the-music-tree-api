from rest_framework import status

from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestCase(GenreTestCase):
    def test_delete_root_criteria_with_children_then_direct_tracks_in_criterialess_playlist_in_first_positions(self):
        genreless_track_added_first = self.model_fixture_factory.create_youtube_track(
            title="genreless first", genre=None
        )
        genreless_track_added_second = self.model_fixture_factory.create_youtube_track(
            title="genreless second", genre=None
        )

        rock_criteria = self.model_fixture_factory.create_genre(name="rock")
        indie_criteria = self.model_fixture_factory.create_genre(name="indie", parent=rock_criteria)

        rock_track_added_third = self.model_fixture_factory.create_youtube_track(
            title="rock third", genre=rock_criteria
        )
        indie_track_added_fourth = self.model_fixture_factory.create_youtube_track(
            title="indie fourth", genre=indie_criteria
        )
        rock_track_added_fifth = self.model_fixture_factory.create_youtube_track(
            title="rock fifth", genre=rock_criteria
        )

        response = self._delete_genre(uuid=rock_criteria.uuid)

        assert response.status_code == status.HTTP_204_NO_CONTENT

        genreless_playlist = GenrePlaylist.objects.get(user=self.system_user, criteria=None)
        tracks_dict_by_position = genreless_playlist.tracks_not_archived_dict_by_position
        assert len(tracks_dict_by_position) == 4
        assert tracks_dict_by_position[1].uuid == rock_track_added_fifth.uuid
        assert tracks_dict_by_position[2].uuid == rock_track_added_third.uuid
        assert tracks_dict_by_position[3].uuid == genreless_track_added_second.uuid
        assert tracks_dict_by_position[4].uuid == genreless_track_added_first.uuid

        indie_playlist = GenrePlaylist.objects.get(criteria=indie_criteria)
        assert indie_playlist.is_root
        indie_tracks_dict_by_position = indie_playlist.tracks_not_archived_dict_by_position
        assert len(indie_tracks_dict_by_position) == 1
        assert indie_tracks_dict_by_position[1].uuid == indie_track_added_fourth.uuid
