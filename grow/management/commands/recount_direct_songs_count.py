from django.core.management.base import BaseCommand
from django.db import connection, transaction

from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.song.Song import Song
from grow.track.direct_songs_count import recount_direct_songs_count_holding_writers


class Command(BaseCommand):
    help = (
        "Recount every canonical genre playlist's direct songs count from the songs. Run once after deploying 0094: "
        "songs the previous release created while the migration ran are not in its count."
    )

    def handle(self, *args, **options) -> None:
        with transaction.atomic():
            recount_direct_songs_count_holding_writers(Song, CriteriaPlaylist, connection)
        self.stdout.write("direct_songs_count recounted")
