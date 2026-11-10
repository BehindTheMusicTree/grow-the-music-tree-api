import pytest
from django.db import connection
from django.test.utils import override_settings

from grow.view.viewset.model.playlist.RegionPlaylistTracksMixin import RegionPlaylistTracksMixin
from perf.conftest import largest_genre_playlist


class _Mixin(RegionPlaylistTracksMixin):
    request = None


def _explain(sql: str, params: tuple) -> str:
    with connection.cursor() as cursor:
        # The pinned fixture is ~9k songs, where a sequential scan legitimately beats any index. Forbidding it checks
        # what this scale can prove: the query's predicate is one the partial index can answer. Whether prod's planner
        # prefers it at ~31M rows is only observable on the VPS.
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(f"EXPLAIN (COSTS OFF) {sql}", params)
        return "\n".join(row[0] for row in cursor.fetchall())


@pytest.mark.django_db
@override_settings(VIEWER_CONTEXT_TOKEN="")
def test_open_playable_probe_can_be_answered_by_the_partial_index():
    playlist = largest_genre_playlist()
    queryset = _Mixin().get_track_playlist_rel_queryset(playlist).filter(playlist=playlist).values("pk")
    sql, params = queryset.query.sql_with_params()
    plan = _explain(sql, params)
    assert "Index Only Scan using grow_song_open_playable_idx" in plan, plan
