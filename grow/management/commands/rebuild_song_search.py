from django.core.management.base import BaseCommand, CommandError

from grow.model.song_search.SongSearch import SongSearch
from grow.song_search.rebuild import rebuild_song_search


class Command(BaseCommand):
    help = (
        "Rebuild the song search projection from the songs and swap it in; search answers 503 until the first run. "
        "With --check, only report how far the projection drifted from the songs and fail if it did."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--check", action="store_true", help="Report drift instead of rebuilding.")

    def handle(self, *args, check: bool = False, **options) -> None:
        if check:
            drift = SongSearch.objects.drift()
            self.stdout.write(", ".join(f"{name}={count}" for name, count in drift.items()))
            if any(drift.values()):
                raise CommandError("The song search projection drifted from the songs; run rebuild_song_search")
            return
        rows = rebuild_song_search()
        self.stdout.write(f"song search rebuilt: {rows} songs")
