import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TransactionTestCase

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.user.get_prototype_user import get_prototype_user
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack


class SeedPrototypeTreeTests(TransactionTestCase):
    """
    Uses TransactionTestCase (real commits) rather than TestCase: SQLite only
    enforces Track.genre's FK on commit, so TestCase's savepoint-wrapped tests
    never actually hit the constraint violation a second `import_criteria_tree`
    call triggers against tracks left over from the first (Track.genre is
    on_delete=DO_NOTHING, so wiping the old genre tree doesn't clear them).
    A single test method is used deliberately: TransactionTestCase flushes the
    database between tests, and re-serializing/restoring the migration-seeded
    lookup rows (prototype user, CriteriaType) across multiple test methods is
    more fragile than just asserting everything in one pass.
    """

    serialized_rollback = True

    def test_seeding_is_idempotent_and_uses_dedicated_prototype_content(self):
        user = get_prototype_user()

        call_command("seed_prototype_tree")
        genre_count = Genre.objects.filter(user=user).count()
        track_count = YoutubeTrack.objects.filter(user=user).count()
        assert genre_count > 0
        assert track_count > 0
        assert Genre.objects.filter(user=user, name="Deep House").exists()
        assert YoutubeTrack.objects.filter(user=user, title="Prototype Deep House Cut").exists()

        call_command("seed_prototype_tree")
        assert Genre.objects.filter(user=user).count() == genre_count
        assert YoutubeTrack.objects.filter(user=user).count() == track_count

        external_songs = [
            {
                "title": "External Deep House Cut",
                "artist": "External Demo Artist",
                "youtube_video_id": "EXTERNAL_01",
                "genre_name": "Deep House",
            },
            {
                "title": "External Unmatched Genre Cut",
                "artist": "External Demo Artist",
                "youtube_video_id": "EXTERNAL_02",
                "genre_name": "Nonexistent Genre",
            },
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as songs_file:
            json.dump(external_songs, songs_file)
            songs_file_path = songs_file.name
        try:
            call_command("seed_prototype_tree", songs_file=songs_file_path)
        finally:
            Path(songs_file_path).unlink()

        assert YoutubeTrack.objects.filter(user=user, title="External Deep House Cut").exists()
        assert not YoutubeTrack.objects.filter(user=user, title="Prototype Deep House Cut").exists()
        assert not YoutubeTrack.objects.filter(user=user, title="External Unmatched Genre Cut").exists()
