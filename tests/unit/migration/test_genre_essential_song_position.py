from importlib import import_module
from types import SimpleNamespace

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from grow.model.criteria.children.genre.GenreEssentialSong import GenreEssentialSong
from grow.model.curation.CurationEntry import CurationEntry
from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0123_genre_essential_song_position")

MBIDS = [f"{n}{n}{n}{n}{n}{n}{n}{n}-1111-4111-8111-111111111111" for n in "123"]


class TestCase(AppTestCase):
    def test_backfill_then_rule_positions_first_and_unnamed_rows_last_by_pk(self):
        genre = self.model_fixture_factory.create_genre("Rock", wikidata_id="Q11399")
        songs = [
            self.model_fixture_factory.create_song(f"S{i}", genre, musicbrainz_recording_id=mbid)
            for i, mbid in enumerate(MBIDS)
        ]
        # Stored order: song 0, 1, 2 (arbitrary positions, as before the backfill). The rules name 2 then 0.
        for offset, song in enumerate(songs):
            GenreEssentialSong.objects.create(genre=genre, song=song, position=90 + offset)
        for mbid, position in ((MBIDS[2], "1"), (MBIDS[0], "2")):
            CurationEntry.objects.create(
                user=None, list_name="essential_songs", key=f"Q11399\t{mbid}", values={"position": position}
            )
        apps = MigrationLoader(connection).project_state(("grow", "0123_genre_essential_song_position")).apps

        migration_module.backfill_positions(apps, SimpleNamespace(connection=connection))

        rows = GenreEssentialSong.objects.filter(genre=genre)
        assert [str(r.song.musicbrainz_recording_id) for r in rows] == [MBIDS[2], MBIDS[0], MBIDS[1]]
        assert [r.position for r in rows] == [1, 2, 3]

    def test_one_unique_constraint_per_column_set(self):
        """The auto through table's (genre, song) unique is dropped, not kept beside the named one."""
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, GenreEssentialSong._meta.db_table)
        uniques = [tuple(c["columns"]) for c in constraints.values() if c["unique"] and not c["primary_key"]]
        assert sorted(uniques) == [("genre_id", "position"), ("genre_id", "song_id")]
