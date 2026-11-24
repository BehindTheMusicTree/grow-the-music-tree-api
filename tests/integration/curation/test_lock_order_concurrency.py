from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.song.Song import Song
from grow.model.song.SongCurationManager import SongCurationManager
from grow.model.user.UserProfile import UserProfile
from tests.integration.criteria.playlist.test_catalogue_projection_concurrency import in_connection
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def test_curation_and_song_assignment_take_locks_in_one_order():
    """Gate, then curation lock, then rows: concurrent genre edits and song assignments never deadlock."""
    factory = ModelFixtureFactory(default_user=None)
    actor = get_user_model().objects.create_user(username="curator")
    UserProfile.objects.create(user=actor, pseudo="curator")
    genre = factory.create_genre("Lock order A", wikidata_id="Q900001")
    other = factory.create_genre("Lock order B", wikidata_id="Q900002")
    songs = [
        factory.create_song(
            f"Lock order {i}", genre, musicbrainz_recording_id=f"00000000-0000-4000-8000-00000000000{i}"
        )
        for i in range(6)
    ]

    def assign(i: int):
        song = Song.objects.get(pk=songs[i].pk)
        target = other if i % 2 else genre
        return in_connection(lambda: SongCurationManager().assign_genre([song], target, actor))

    def edit(i: int):
        instance = Genre.objects.get(pk=genre.pk)
        return in_connection(lambda: Genre.objects.update_instance(instance, actor=actor, summary=f"s{i}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(assign, i) for i in range(6)] + [pool.submit(edit, i) for i in range(6)]
        for future in futures:
            future.result(timeout=30)
