from django.core.management.base import BaseCommand, CommandError

from grow.genre_music.catalogue_verification import song_membership_drift_summary


class Command(BaseCommand):
    help = "Verify, in one set-based query, that every song's membership genre matches its derived genre."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default")
        parser.add_argument("--sample", type=int, default=20)

    def handle(self, *args, **options):
        count, sample = song_membership_drift_summary(using=options["database"], sample=options["sample"])
        if count:
            raise CommandError(f"{count} songs with a drifted membership genre, e.g. {', '.join(map(str, sample))}")
        self.stdout.write(self.style.SUCCESS("Verified song membership genres"))
