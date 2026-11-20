from django.core.management.base import BaseCommand, CommandError

from grow.artist_song.rebuild import is_current, rebuild_artist_song, stamp_current
from grow.model.artist_song.ArtistSong import ArtistSong
from grow.model.artist_song.ArtistSongState import ArtistSongState


class Command(BaseCommand):
    help = (
        "Rebuild the artist song projection from the songs and swap it in; `?artist` song lists answer 503 until the "
        "first run. With --check, only report how far the projection drifted from the songs and fail if it did."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Report drift instead of rebuilding; a clean check records the current definition's fingerprint.",
        )
        parser.add_argument(
            "--if-stale",
            action="store_true",
            help="Skip the rebuild when the table was built (or verified) by the current definition.",
        )

    def handle(self, *args, check: bool = False, if_stale: bool = False, **options) -> None:
        if check and if_stale:
            raise CommandError("--check and --if-stale are mutually exclusive")
        if check:
            drift = ArtistSong.objects.drift()
            self.stdout.write(", ".join(f"{name}={count}" for name, count in drift.items()))
            if any(drift.values()):
                raise CommandError("The artist song projection drifted from the songs; run rebuild_artist_song")
            self.stdout.write(f"fingerprint stamped: {stamp_current()}")
            return
        if if_stale and is_current():
            self.stdout.write(f"artist song current: {ArtistSongState.load().fingerprint}")
            return
        rows = rebuild_artist_song()
        self.stdout.write(f"artist song rebuilt: {rows} links")
