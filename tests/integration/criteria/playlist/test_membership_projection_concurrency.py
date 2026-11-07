from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection, transaction
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.track.Track import Track

from grow.genre_music.membership import (
    membership_bucket_counts,
    stored_membership_bucket_counts,
    verify_membership_counts,
)
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from tests.utils.ModelFixtureFactory import ModelFixtureFactory


def in_connection(operation):
    close_old_connections()
    try:
        operation()
    finally:
        close_old_connections()


def exercise_race(second_write):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL writer-lock semantics")
    factory = ModelFixtureFactory(default_user=None)
    old = factory.create_genre(f"Old {second_write}")
    new = factory.create_genre(f"New {second_write}")
    song = factory.create_song("Song", genre=old)
    playlist = GenrePlaylist.objects.get(criteria=old)
    TrackPlaylistRel.objects.filter(playlist=playlist, track=song).delete()
    gate_held = Event()
    release = Event()
    second_started = Event()
    second_finished = Event()

    def move():
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
            Track.objects.filter(pk=song.pk).update(genre=new)
            gate_held.set()
            if not release.wait(5):
                raise TimeoutError("Concurrent writer did not release the test gate")

    def write():
        second_started.set()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
            if second_write == "insert":
                TrackPlaylistRel.objects.create(playlist=playlist, track=song, user=None)
            else:
                verify_membership_counts(repair=True)
        second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(in_connection, move)
        try:
            assert gate_held.wait(5)
            second = pool.submit(in_connection, write)
            assert second_started.wait(5)
            assert not second_finished.wait(0.1), "Writer bypassed source exclusion"
        finally:
            release.set()
        first.result(timeout=10)
        second.result(timeout=10)
    assert stored_membership_bucket_counts() == membership_bucket_counts()
    if second_write == "insert":
        assert stored_membership_bucket_counts()[(playlist.pk, new.pk)] == 1


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_genre_move_serializes_with_membership_insert_and_repair():
    # Earlier transaction tests flush migration seed rows. This test commits writes
    # across connections, so establish its own reference configuration explicitly.
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    exercise_race("insert")
    exercise_race("repair")
