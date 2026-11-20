"""The export plan against the migrated Postgres schema (#511)."""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from benchmarks.catalogue import catalogue_restore as catalogue
from grow.artist_song.rebuild import stamp_current as stamp_artist_song
from grow.model.artist_song.ArtistSongState import ArtistSongState
from grow.model.song_search.SongSearchState import SongSearchState
from grow.song_search.rebuild import stamp_current as stamp_song_search

pytestmark = [pytest.mark.postgres, pytest.mark.django_db]


def _plan() -> dict:
    out = StringIO()
    call_command("export_perf_catalogue", plan=True, stdout=out)
    return json.loads(out.getvalue())


def _ready() -> None:
    for state in (SongSearchState, ArtistSongState):
        state.objects.update_or_create(pk=1, defaults={"ready": True})
    stamp_song_search()
    stamp_artist_song()


def test_plan_of_a_stamped_database():
    _ready()
    plan = _plan()
    assert plan["data_tables"] == sorted(catalogue.RETAIN | catalogue.DERIVED)
    assert plan["projections"]["grow_song_search"]["fingerprint"] == SongSearchState.load().fingerprint
    assert plan["projections"]["grow_artist_song"]["fingerprint"] == ArtistSongState.load().fingerprint


def test_plan_fails_when_the_database_is_not_stamped_without_writing_state():
    with pytest.raises(CommandError, match="rebuild_song_search --check"):
        _plan()
    assert not SongSearchState.objects.exists()
    assert not ArtistSongState.objects.exists()


def test_plan_fails_when_the_live_schema_drifted():
    _ready()
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE grow_unclassified_probe (id integer)")
    with pytest.raises(CommandError, match="schema drift"):
        _plan()


def test_plan_fails_when_a_stamp_is_stale():
    _ready()
    ArtistSongState.objects.filter(pk=1).update(fingerprint="0" * 64)
    with pytest.raises(CommandError, match="rebuild_artist_song --check"):
        _plan()
