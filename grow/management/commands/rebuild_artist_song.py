from django.core.management.base import BaseCommand, CommandError

from grow.artist_song.rebuild import rebuild_artist_song
from grow.model.artist_song.ArtistSong import ArtistSong


class Command(BaseCommand):
    help = (
        "Rebuild the artist song projection from the songs and swap it in; `?artist` song lists answer 503 until the "
        "first run. With --check, only report how far the projection drifted from the songs and fail if it did."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--check", action="store_true", help="Report drift instead of rebuilding.")

    def handle(self, *args, check: bool = False, **options) -> None:
        if check:
            drift = ArtistSong.objects.drift()
            self.stdout.write(", ".join(f"{name}={count}" for name, count in drift.items()))
            if any(drift.values()):
                raise CommandError("The artist song projection drifted from the songs; run rebuild_artist_song")
            return
        rows = rebuild_artist_song()
        self.stdout.write(f"artist song rebuilt: {rows} links")
