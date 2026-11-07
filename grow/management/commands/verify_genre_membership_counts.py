from django.core.management.base import BaseCommand, CommandError

from grow.genre_music.membership import verify_membership_counts


class Command(BaseCommand):
    help = "Verify actual genre playlist membership buckets; optionally repair them atomically."

    def add_arguments(self, parser):
        parser.add_argument("--repair", action="store_true")
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        expected, actual = verify_membership_counts(repair=options["repair"], using=options["database"])
        mismatches = sum(expected.get(key) != actual.get(key) for key in expected.keys() | actual.keys())
        if mismatches and not options["repair"]:
            raise CommandError(f"{mismatches} inconsistent genre membership buckets; run with --repair to rebuild")
        if mismatches:
            self.stdout.write(self.style.SUCCESS(f"Repaired {mismatches} genre membership buckets"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Verified {len(expected)} genre membership buckets"))
