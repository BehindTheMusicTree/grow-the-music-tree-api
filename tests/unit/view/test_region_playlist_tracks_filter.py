import pytest

from grow.model.song.playable import RESTRICTED_POLICY
from grow.model.song.Song import Song
from grow.view.viewset.model.playlist.RegionPlaylistTracksMixin import RegionPlaylistTracksMixin


class _Playlist:
    pk = 1


class _Mixin(RegionPlaylistTracksMixin):
    request = None


@pytest.mark.django_db
def test_region_filter_is_one_top_level_anti_join_without_playable_probe():
    sql = str(_Mixin().get_track_playlist_rel_queryset(_Playlist()).values("pk").query)
    where = sql.split("WHERE", 1)[1]
    assert where.count("EXISTS(") == 1
    assert "NOT EXISTS(" in where
    assert "youtube_video_id" not in where


def test_restricted_policy_matches_the_partial_index_condition():
    index = next(i for i in Song._meta.indexes if i.name == "grow_song_restricted_idx")
    assert index.condition == RESTRICTED_POLICY
    assert index.fields == ["track"]
    assert index.include == ("youtube_region_restriction",)
