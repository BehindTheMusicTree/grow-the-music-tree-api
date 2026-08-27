import json
from pathlib import Path

from django.core.management.base import BaseCommand
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.serializer import (
    CriteriaTreeImportSerializer,
)
from the_music_tree_genre_kit.serializer.model.track.input.song_example.Fields import (
    Fields as SongExampleFields,
)
from the_music_tree_genre_kit.serializer.model.track.input.song_example.import_serializer import (
    SongExampleImportSerializer,
)

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.user.get_prototype_user import get_prototype_user
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack

PROTOTYPE_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class Command(BaseCommand):
    help = "(Re)seeds the prototype user's genre tree and tracks from grow/data/prototype_*.json"

    def handle(self, *args, **options):
        user = get_prototype_user()

        # Track.genre is on_delete=DO_NOTHING; clear tracks first or re-seeding violates the FK constraint when the genre tree is wiped.
        YoutubeTrack.objects.filter(user=user).delete()

        tree_data = json.loads((PROTOTYPE_DATA_DIR / "prototype_genre_tree.json").read_text())
        tree_serializer = CriteriaTreeImportSerializer(data={"tree": tree_data["tree"]})
        tree_serializer.is_valid(raise_exception=True)
        Genre.objects.import_criteria_tree(user, tree_serializer.validated_data)

        songs_data = json.loads((PROTOTYPE_DATA_DIR / "prototype_songs.json").read_text())
        songs_serializer = SongExampleImportSerializer(data={SongExampleFields.SONGS: songs_data})
        songs_serializer.is_valid(raise_exception=True)
        YoutubeTrack.objects.import_example_songs(user, songs_serializer.validated_data[SongExampleFields.SONGS])

        self.stdout.write(self.style.SUCCESS(f"Seeded prototype tree for user '{user.username}'"))
