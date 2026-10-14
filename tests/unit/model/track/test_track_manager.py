from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from grow.model.recording.Recording import Recording
from tests.utils.AppTestCase import AppTestCase


class TestCase(AppTestCase):
    def test_update_instance_genre_change_without_actor_does_not_lock_and_logs_pipeline_history(self):
        rock = self.model_fixture_factory.create_genre(name="Rock")
        pop = self.model_fixture_factory.create_genre(name="Pop")
        track = self.model_fixture_factory.create_recording(title="wech", genre=rock)

        updated = Recording.objects.update_instance(track, genre=pop)

        assert updated.is_manually_edited is False
        entry = HistoryEntry.objects.get(content_uuid=track.uuid, action=HistoryAction.GENRE_CHANGED)
        assert entry.actor is None
        assert entry.old_value == "Rock"
        assert entry.new_value == "Pop"

    def test_update_instance_genre_change_with_actor_locks_and_logs_admin_history(self):
        rock = self.model_fixture_factory.create_genre(name="Rock")
        pop = self.model_fixture_factory.create_genre(name="Pop")
        track = self.model_fixture_factory.create_recording(title="wech", genre=rock)

        updated = Recording.objects.update_instance(track, genre=pop, actor=self.admin)

        assert updated.is_manually_edited is True
        entry = HistoryEntry.objects.get(content_uuid=track.uuid, action=HistoryAction.GENRE_CHANGED)
        assert entry.actor == self.admin

    def _playlist_ids(self, track: Recording) -> set:
        return set(TrackPlaylistRel.objects.filter(track=track).values_list("playlist_id", flat=True))

    def test_create_only_playable_recording_joins_genre_playlists(self):
        rock = self.model_fixture_factory.create_genre(name="Rock")
        playable = self.model_fixture_factory.create_recording(title="Playable", genre=rock)
        no_video = self.model_fixture_factory.create_recording(title="No video", genre=rock, youtube_video_id=None)
        blocked = self.model_fixture_factory.create_recording(
            title="Blocked", genre=rock, youtube_unplayable_reason="not_embeddable"
        )

        assert self._playlist_ids(playable) == {rock.criteria_playlist.pk}
        assert self._playlist_ids(no_video) == self._playlist_ids(blocked) == set()

    def test_update_instance_linking_a_video_joins_genre_playlists(self):
        rock = self.model_fixture_factory.create_genre(name="Rock")
        prog = self.model_fixture_factory.create_genre(name="Progressive Rock", parent=rock)
        track = self.model_fixture_factory.create_recording(title="wech", genre=prog, youtube_video_id=None)

        Recording.objects.update_instance(track, youtube_video_id="abc123defgh")

        assert self._playlist_ids(track) == {rock.criteria_playlist.pk, prog.criteria_playlist.pk}

    def test_update_instance_becoming_unplayable_leaves_playlists_and_renumbers(self):
        rock = self.model_fixture_factory.create_genre(name="Rock")
        older = self.model_fixture_factory.create_recording(title="Older", genre=rock)
        track = self.model_fixture_factory.create_recording(title="wech", genre=rock)

        Recording.objects.update_instance(track, youtube_unplayable_reason="not_embeddable")

        assert self._playlist_ids(track) == set()
        assert list(TrackPlaylistRel.objects.filter(track=older).values_list("position", flat=True)) == [1]
