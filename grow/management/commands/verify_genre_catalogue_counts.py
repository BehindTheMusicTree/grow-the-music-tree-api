from django.core.management.base import BaseCommand, CommandError

from grow.genre_music.catalogue_verification import verify_catalogue_counts


class Command(BaseCommand):
    help = "Verify canonical Song catalogue counts against both projections; optionally repair them atomically."

    def add_arguments(self, parser):
        parser.add_argument("--repair", action="store_true")
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        try:
            reports = verify_catalogue_counts(repair=options["repair"], using=options["database"])
        except (ValueError, RuntimeError) as error:
            raise CommandError(str(error)) from error
        for name, report in reports.items():
            self.stdout.write(
                f"{name}: {len(report.mismatches)} mismatches, {len(report.negatives)} negatives, "
                f"{len(report.unexpected)} unexpected buckets, {len(report.missing_playlists)} missing playlists"
            )
            for key, (expected, actual) in sorted(report.mismatches.items(), key=lambda item: str(item[0])):
                self.stdout.write(f"  {key or 'genreless'}: expected={expected}, stored={actual}")
            for label, keys in (("unexpected", report.unexpected), ("missing playlist", report.missing_playlists)):
                for key in sorted(keys, key=str):
                    self.stdout.write(f"  {label}: {key or 'genreless'}")
        if any(not report.valid for report in reports.values()):
            if not options["repair"]:
                raise CommandError("Catalogue drift detected; use --repair for an explicit rebuild")
            self.stdout.write(self.style.SUCCESS("Repaired and independently verified catalogue counts"))
        else:
            self.stdout.write(self.style.SUCCESS("Verified catalogue counts"))
