import uuid

from django.db import models
from django.db.models import Q


class CurationApplyRequest(models.Model):
    """An admin request to rebuild the canonical tree and songs from current curation, run by the pipeline's poller."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        SUPERSEDED = "superseded"

    class Stage(models.TextChoices):
        FETCHING_RULES = "fetching_rules"
        BUILDING_GENRES = "building_genres"
        MATCHING_SONGS = "matching_songs"
        IMPORTING_TREE = "importing_tree"
        UPLOADING_SONGS = "uploading_songs"
        MERGING_SONGS = "merging_songs"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.TextField(choices=Status.choices, default=Status.QUEUED)
    stage = models.TextField(choices=Stage.choices, null=True)
    stage_current = models.PositiveIntegerField(null=True)
    stage_total = models.PositiveIntegerField(null=True)
    error = models.TextField(null=True)
    requested_on = models.DateTimeField(auto_now_add=True)
    started_on = models.DateTimeField(null=True)
    finished_on = models.DateTimeField(null=True)

    class Meta:
        db_table = "grow_curation_apply_request"
        constraints = [
            # One constant per active row: at most one request queued or running at a time.
            models.UniqueConstraint(
                models.Value(True, output_field=models.BooleanField()),
                condition=Q(status__in=["queued", "running"]),
                name="curation_apply_request_single_active",
            )
        ]
