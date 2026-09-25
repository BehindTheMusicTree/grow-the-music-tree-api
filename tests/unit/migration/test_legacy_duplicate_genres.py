from importlib import import_module

from django.apps import apps
from django.db import connection

from grow.model.criteria.children.genre.Genre import Genre
from tests.utils.AppTestCase import AppTestCase

delete_legacy_duplicate_genres = import_module(
    "grow.migrations.0026_backfill_genre_source"
).delete_legacy_duplicate_genres


class TestCase(AppTestCase):
    def test_legacy_duplicate_is_deleted_and_its_tracks_and_children_are_reparented(self):
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX unique_canonical_name")
        rock = self.model_fixture_factory.create_genre(name="Rock", wikidata_id="Q11399")
        legacy_parent = self.model_fixture_factory.create_genre(name="legacy root")
        legacy = self.model_fixture_factory.create_genre(name="rock", parent=legacy_parent)
        child = self.model_fixture_factory.create_genre(name="Child", parent=legacy)
        track = self.model_fixture_factory.create_youtube_track(title="Song", genre=legacy)

        delete_legacy_duplicate_genres(apps, None)

        assert not Genre.objects.filter(pk=legacy.pk).exists()
        assert Genre.objects.filter(pk__in=[rock.pk, legacy_parent.pk]).count() == 2
        track.refresh_from_db()
        child.refresh_from_db()
        assert track.genre_id == legacy_parent.pk
        assert child.parent_id == legacy_parent.pk
