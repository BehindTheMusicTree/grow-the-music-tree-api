import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext, override_settings
from rest_framework.request import Request
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.view.viewset.model.playlist.children.criteria.genre.GenrePlaylistViewSet import GenrePlaylistViewSet
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


def _plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


@pytest.mark.django_db
def test_blocked_count_never_probes_the_track_table_per_member():
    """The `blocked` term of `get_tracks_count` filters the genre on the membership row, not through the song table."""
    playlist = largest_genre_playlist()
    request = Request(
        RequestFactory().get(
            "/",
            {"coverage": "genre_and_subgenres", "subgenres": "regional"},
            HTTP_X_VIEWER_COUNTRY="FR",
            HTTP_X_VIEWER_CONTEXT_TOKEN="t",
        )
    )
    viewset = GenrePlaylistViewSet()
    viewset.request = request
    with override_settings(VIEWER_CONTEXT_TOKEN="t"), CaptureQueriesContext(connection) as captured:
        viewset.get_track_playlist_rel_queryset(playlist)
        viewset.get_tracks_count()
    sql = captured.captured_queries[-1]["sql"]
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
        plan = cursor.fetchone()[0][0]["Plan"]
    members = TrackPlaylistRel.objects.filter(playlist=playlist).count()
    # A per-member probe loops once per membership row; a blocked-member join loops at most once per blocked member.
    probes = [
        node["Actual Loops"]
        for node in _plan_nodes(plan)
        if node.get("Relation Name") == "the_music_tree_genre_kit_track" and node["Actual Loops"] >= members
    ]
    assert probes == [], plan
