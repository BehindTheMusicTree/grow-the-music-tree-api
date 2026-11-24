from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from grow.genre_music.catalogue_verification import song_membership_drift, song_membership_drift_summary
from grow.model.song.Song import Song
from tests.utils.ModelFixtureFactory import ModelFixtureFactory
from tests.utils.song_graph import install_song_graph

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


def assert_parity():
    """The set-based SQL must agree with the Python oracle on count and on the sampled ids."""
    oracle = song_membership_drift()
    count, sample = song_membership_drift_summary()
    assert count == len(oracle)
    assert sample == sorted(oracle)[:20]
    return oracle


def drift(song, genre=None):
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
    Song.objects.filter(pk=song.pk).update(membership_genre=genre)


def test_without_dataset_the_track_genre_is_derived():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Legacy")
    song = factory.create_song("Song", genre)
    factory.create_song("Genreless", None)
    assert assert_parity() == {}
    drift(song, None)
    assert assert_parity() == {song.pk: (genre.pk, None)}


def test_with_dataset_the_attributed_genre_is_derived():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Semantic")
    factory.create_genre("Outside the graph")
    song = factory.create_song("Song", None)
    factory.create_song("Unattributed", None)
    install_song_graph({genre: [song]})
    assert assert_parity() == {}
    drift(song, None)
    assert assert_parity() == {song.pk: (genre.pk, None)}


def test_stale_legacy_genre_after_dataset_creation_and_wrong_genre_are_drift():
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    semantic = factory.create_genre("Semantic")
    song = factory.create_song("Song", legacy)
    other = factory.create_song("Other", None)
    install_song_graph({legacy: [], semantic: [song]})
    assert assert_parity() == {}
    drift(song, legacy)
    drift(other, semantic)
    assert set(assert_parity()) == {song.pk, other.pk}


def test_inactive_node_derives_no_genre():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Semantic")
    song = factory.create_song("Song", None)
    dataset = install_song_graph({genre: [song]})
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
    dataset.nodes.update(is_active=False)
    assert set(assert_parity()) == {song.pk}


def test_sample_is_bounded():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Legacy")
    songs = [factory.create_song(f"Song {number}", genre) for number in range(3)]
    for song in songs:
        drift(song, None)
    count, sample = song_membership_drift_summary(sample=2)
    assert count == 3
    assert sample == sorted(song.pk for song in songs)[:2]


def test_command_fails_on_drift_and_passes_when_clean():
    factory = ModelFixtureFactory(None)
    genre = factory.create_genre("Legacy")
    song = factory.create_song("Song", genre)
    call_command("verify_song_membership", stdout=StringIO())
    drift(song, None)
    with pytest.raises(CommandError, match="1 songs"):
        call_command("verify_song_membership", stdout=StringIO())
