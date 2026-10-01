from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from grow.curation.rows import import_csv_dir
from grow.model.curation.CurationEntry import CurationEntry


class Command(BaseCommand):
    help = "Upsert every curation list from the manual_<list_name>.csv files in a directory."

    def add_arguments(self, parser):
        parser.add_argument("directory", type=Path)

    def handle(self, *args, directory: Path, **options) -> None:
        try:
            with transaction.atomic():
                results = import_csv_dir(directory, CurationEntry.objects.upsert)
        except (OSError, ValueError) as e:
            raise CommandError(str(e)) from e
        self.stdout.write(
            f"{results['created']} created, {results['updated']} updated, {results['unchanged']} unchanged"
        )
