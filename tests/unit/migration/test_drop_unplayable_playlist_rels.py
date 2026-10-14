from importlib import import_module
from types import SimpleNamespace

from django.db import connection
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.model.recording.Recording import Recording
from tests.utils.AppTestCase import AppTestCase

migration_module = import_module("grow.migrations.0051_drop_unplayable_playlist_rels")


class TestCase(AppTestCase):
    def test_unplayable_rels_dropped_and_positions_closed(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        kept = self.model_fixture_factory.create_recording(title="Kept", genre=rock)
        no_video = self.model_fixture_factory.create_recording(title="No video", genre=rock)
        blocked = self.model_fixture_factory.create_recording(title="Blocked", genre=rock)
        newest = self.model_fixture_factory.create_recording(title="Newest", genre=rock)
        # Bypasses the manager, like the rows left behind by the former always-add behaviour.
        Recording.objects.filter(pk=no_video.pk).update(youtube_video_id=None)
        Recording.objects.filter(pk=blocked.pk).update(youtube_unplayable_reason="not_embeddable")

        migration_module.drop_unplayable_playlist_rels(None, SimpleNamespace(connection=connection))

        rels = TrackPlaylistRel.objects.filter(playlist=rock.criteria_playlist).order_by("position")
        assert list(rels.values_list("track_id", "position")) == [(newest.pk, 1), (kept.pk, 2)]
