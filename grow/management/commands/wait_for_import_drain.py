import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from grow.bulk_import.ImportAttempt import ImportAttempt, ImportReceipt
from grow.bulk_import.merge_lock import merge_is_live

logger = logging.getLogger(__name__)

ACTIVE_STATES = (ImportAttempt.State.RUNNING, ImportAttempt.State.COMMITTING, ImportAttempt.State.CLEANING_UP)


def live_attempts() -> list[ImportAttempt]:
    """Active attempts whose worker still holds the run's advisory lock; a dead worker never blocks a deploy."""
    attempts = ImportAttempt.objects.filter(state__in=ACTIVE_STATES).order_by("run_id", "attempt")
    live = [attempt for attempt in attempts if merge_is_live(attempt.run_id)]
    # A queued finalization (receipt present) holds no lock yet but a restart would drop its queue entry.
    pending = ImportAttempt.objects.filter(
        state=ImportAttempt.State.QUEUED, run_id__in=ImportReceipt.objects.values("run_id")
    ).order_by("run_id", "attempt")
    return live + list(pending)


class Command(BaseCommand):
    help = "Wait until no import merge is running, so a deploy does not kill one. Exits 1 on timeout."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, required=True, help="Seconds to wait before failing")
        parser.add_argument("--interval", type=int, default=30, help="Seconds between checks")

    def handle(self, *args, timeout, interval, **options):
        deadline = time.monotonic() + timeout
        while True:
            active = live_attempts()
            if not active:
                self.stdout.write("No import running.")
                return
            now = timezone.now()
            summary = ", ".join(
                f"run={a.run_id} kind={a.kind} step={a.step} age={int((now - (a.started_at or a.queued_at)).total_seconds())}s"
                for a in active
            )
            if time.monotonic() >= deadline:
                raise CommandError(f"imports still running after {timeout}s: {summary}")
            self.stdout.write(f"Waiting for imports: {summary}")
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
