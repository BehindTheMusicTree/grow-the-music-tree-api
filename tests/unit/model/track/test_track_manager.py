from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_update_instance_genre_change_without_actor_does_not_lock_and_logs_pipeline_history(self):
        rock = self.model_fixture_factory.create_genre(name="Rock")
        pop = self.model_fixture_factory.create_genre(name="Pop")
        track = self.model_fixture_factory.create_youtube_track(title="wech", genre=rock)

        updated = YoutubeTrack.objects.update_instance(track, genre=pop)

        assert updated.is_manually_edited is False
        entry = HistoryEntry.objects.get(content_uuid=track.uuid, action=HistoryAction.GENRE_CHANGED)
        assert entry.actor_email is None
        assert entry.old_value == "Rock"
        assert entry.new_value == "Pop"

    def test_update_instance_genre_change_with_actor_locks_and_logs_admin_history(self):
        rock = self.model_fixture_factory.create_genre(name="Rock")
        pop = self.model_fixture_factory.create_genre(name="Pop")
        track = self.model_fixture_factory.create_youtube_track(title="wech", genre=rock)

        updated = YoutubeTrack.objects.update_instance(track, genre=pop, actor="admin@example.com")

        assert updated.is_manually_edited is True
        entry = HistoryEntry.objects.get(content_uuid=track.uuid, action=HistoryAction.GENRE_CHANGED)
        assert entry.actor_email == "admin@example.com"
