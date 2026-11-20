import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from benchmarks.catalogue.catalogue_restore import inventory_sql
from benchmarks.catalogue.export_plan import build_plan
from grow.artist_song import rebuild as artist_song
from grow.model.artist_song.ArtistSongState import ArtistSongState
from grow.model.song_search.SongSearchState import SongSearchState
from grow.song_search import rebuild as song_search


class Command(BaseCommand):
    help = (
        "Print the catalogue export plan as JSON (read-only, runs no pg_dump). It fails when the schema drifted from "
        "the reviewed inventory or a projection is not stamped with the deployed definition."
    )

    def add_arguments(self, parser):
        parser.add_argument("--plan", action="store_true", help="Print the export plan.")

    def handle(self, *args, plan: bool = False, **options) -> None:
        if not plan:
            raise CommandError("--plan is required")
        if connection.vendor != "postgresql":
            raise CommandError("The export plan reads the PostgreSQL catalogue")
        with connection.cursor() as cursor:
            cursor.execute(inventory_sql())
            inventory = "\n".join(row[0] for row in cursor.fetchall()) + "\n"
        fingerprints = {}
        for table, module, state, rebuild in (
            ("grow_song_search", song_search, SongSearchState, "rebuild_song_search"),
            ("grow_artist_song", artist_song, ArtistSongState, "rebuild_artist_song"),
        ):
            if not module.is_current():
                raise CommandError(f"{table} is not stamped with the deployed definition; run {rebuild} --check")
            fingerprints[table] = state.load().fingerprint
        try:
            export_plan = build_plan(inventory, fingerprints)
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(export_plan, indent=2))
