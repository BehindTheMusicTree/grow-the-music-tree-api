from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from grow.model.curation.CurationSyncState import CurationSyncState

if TYPE_CHECKING:
    from .PipelineRunRequest import PipelineRunRequest


class PipelineRunRequestManager(models.Manager["PipelineRunRequest"]):
    def expire_stale(self) -> None:
        """A running request whose poller stopped heartbeating is dead: free the queue for the next one."""
        now = timezone.now()
        cutoff = now - timedelta(minutes=settings.PIPELINE_RUN_HEARTBEAT_TIMEOUT_MINUTES)
        self.filter(status=self.model.Status.RUNNING, heartbeat_on__lt=cutoff).update(
            status=self.model.Status.EXPIRED, finished_on=now
        )

    @transaction.atomic
    def claim(self) -> PipelineRunRequest | None:
        """Starts the oldest queued request, or supersedes a curation one when no curation edit is pending anymore."""
        self.expire_stale()
        run = (
            self.filter(status=self.model.Status.QUEUED)
            .order_by("requested_on", "pk")
            .select_for_update(skip_locked=True)
            .first()
        )
        if run is None:
            return None
        now = timezone.now()
        if run.kind == self.model.Kind.CURATION and CurationSyncState.load().pending_count == 0:
            run.status = self.model.Status.SUPERSEDED
            run.finished_on = now
        else:
            run.status = self.model.Status.RUNNING
            run.started_on = run.heartbeat_on = now
        run.save()
        return run

    def request_cancel(self, run: PipelineRunRequest) -> None:
        """A queued request is cancelled outright; a running one is flagged for its poller to stop."""
        now = timezone.now()
        run.cancel_requested_on = run.cancel_requested_on or now
        if run.status == self.model.Status.QUEUED:
            run.status = self.model.Status.CANCELLED
            run.finished_on = now
        run.save()
