import pytest

from grow.model.song.playable import OPEN_PLAYABLE
from grow.model.song.Song import Song
from grow.view.viewset.model.playlist.RegionPlaylistTracksMixin import RegionPlaylistTracksMixin


class _Playlist:
    pk = 1


class _Mixin(RegionPlaylistTracksMixin):
    request = None


@pytest.mark.django_db
def test_playable_check_is_two_per_row_probes_joined_by_or():
    mixin = _Mixin()
    sql = str(mixin.get_track_playlist_rel_queryset(_Playlist()).values("pk").query)
    assert sql.count("EXISTS(") == 2
    assert " OR " in sql.split("WHERE", 1)[1]


def test_open_playable_matches_the_partial_index_condition():
    index = next(i for i in Song._meta.indexes if i.name == "grow_song_open_playable_idx")
    assert index.condition == OPEN_PLAYABLE
    assert index.fields == ["track"]
