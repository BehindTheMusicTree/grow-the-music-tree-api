import uuid

from django.db import models
from django.db.models import Q

from grow.model.pipeline_run.PipelineRunRequestManager import PipelineRunRequestManager


class PipelineRunRequest(models.Model):
    """An admin request for a pipeline run, claimed and executed by the pipeline's poller one at a time.

    `curation` rebuilds the canonical tree and songs from current curation; `full` is the nightly run.
    """

    class Kind(models.TextChoices):
        CURATION = "curation"
        FULL = "full"

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        SUPERSEDED = "superseded"
        CANCELLED = "cancelled"
        EXPIRED = "expired"

    class Stage(models.TextChoices):
        FETCHING_RULES = "fetching_rules"
        INGESTING_MUSICBRAINZ = "ingesting_musicbrainz"
        INGESTING_WIKIDATA = "ingesting_wikidata"
        BUILDING_SONGS = "building_songs"
        BUILDING_GENRES = "building_genres"
        MATCHING_SONGS = "matching_songs"
        IMPORTING_TREE = "importing_tree"
        UPLOADING_SONGS = "uploading_songs"
        MERGING_SONGS = "merging_songs"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.TextField(choices=Kind.choices)
    status = models.TextField(choices=Status.choices, default=Status.QUEUED)
    stage = models.TextField(choices=Stage.choices, null=True)
    stage_current = models.PositiveIntegerField(null=True)
    stage_total = models.PositiveIntegerField(null=True)
    error = models.TextField(null=True)
    requested_on = models.DateTimeField(auto_now_add=True)
    started_on = models.DateTimeField(null=True)
    heartbeat_on = models.DateTimeField(null=True)
    cancel_requested_on = models.DateTimeField(null=True)
    finished_on = models.DateTimeField(null=True)

    objects = PipelineRunRequestManager()

    class Meta:
        db_table = "grow_pipeline_run_request"
        constraints = [
            # One constant per active row: at most one request queued or running at a time, whatever its kind.
            models.UniqueConstraint(
                models.Value(True, output_field=models.BooleanField()),
                condition=Q(status__in=["queued", "running"]),
                name="pipeline_run_request_single_active",
            )
        ]
