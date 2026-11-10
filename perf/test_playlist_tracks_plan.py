import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import override_settings

from grow.view.viewset.model.playlist.RegionPlaylistTracksMixin import RegionPlaylistTracksMixin
from perf.conftest import largest_genre_playlist


class _Mixin(RegionPlaylistTracksMixin):
    request = None


def _explain(sql: str, params: tuple) -> str:
    with connection.cursor() as cursor:
        # The pinned fixture is ~9k songs, where a sequential scan legitimately beats any index. Forbidding it checks
        # that the probe is one an index can answer; prod-scale plans are only observable on the VPS.
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(f"EXPLAIN (COSTS OFF) {sql}", params)
        return "\n".join(row[0] for row in cursor.fetchall())


@pytest.mark.django_db
@pytest.mark.parametrize("country", [None, "FR"])
def test_region_probe_is_an_anti_join_that_never_scans_grow_song(country):
    playlist = largest_genre_playlist()
    request = RequestFactory().get(
        "/", **({"HTTP_X_VIEWER_COUNTRY": country, "HTTP_X_VIEWER_CONTEXT_TOKEN": "t"} if country else {})
    )
    mixin = _Mixin()
    mixin.request = request
    with override_settings(VIEWER_CONTEXT_TOKEN="t"):
        queryset = mixin.get_track_playlist_rel_queryset(playlist).filter(playlist=playlist).values("pk")
        sql, params = queryset.query.sql_with_params()
    plan = _explain(sql, params)
    assert "Seq Scan on grow_song" not in plan, plan
    assert "hashed SubPlan" not in plan, plan
