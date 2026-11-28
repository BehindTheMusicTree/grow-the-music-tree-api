from django.db import models

from grow.model.import_run.ImportRun import ImportRun

# Not an `ImportRun.Kind`: its runs are recorded per tree (global / regional), so `/imports/latest/` never lists it.
GENRE_TREES_KIND = "genre_trees"
GENRE_GRAPH_KIND = "genre_graph"


class BulkImportRun(models.Model):
    """A staged import of one `kind`: parts are uploaded into the kind's staging table, then one commit merges them."""

    class Mode(models.TextChoices):
        FULL = "full"
        DELTA = "delta"

    kind = models.TextField(
        choices=[*ImportRun.Kind.choices, (GENRE_TREES_KIND, "Genre Trees"), (GENRE_GRAPH_KIND, "Genre Graph")]
    )
    # `full`: the run is the whole catalog, so owner rows missing from it are deleted. `delta`: only changed rows plus
    # explicit deletions (`BulkImportDeletion`), nothing else is deleted.
    mode = models.TextField(choices=Mode.choices, default=Mode.FULL)
    created_on = models.DateTimeField(auto_now_add=True)
    committed_on = models.DateTimeField(null=True)
    # Merge start, set under the run's advisory lock; null until a worker picks the merge up. Together with the
    # committer's `user_id`/`record` it lets a merge lost to a worker restart be enqueued again.
    started_on = models.DateTimeField(null=True)
    user_id = models.IntegerField(null=True)
    record = models.BooleanField(default=False)
    # Null tokens identify the legacy transport. Semantic runs require both reviewed tokens
    # and an explicit number of parts per stream, including an empty delta's zero parts.
    graph_revision = models.UUIDField(null=True)
    membership_revision = models.UUIDField(null=True)
    expected_parts = models.JSONField(null=True)
    # The pipeline run this import was made for (`X-Pipeline-Run-Request`), copied onto each attempt.
    pipeline_run_request = models.ForeignKey(
        "grow.PipelineRunRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "grow_bulk_import_run"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(graph_revision__isnull=True, membership_revision__isnull=True, expected_parts__isnull=True)
                    | models.Q(
                        kind=ImportRun.Kind.SONGS,
                        graph_revision__isnull=False,
                        membership_revision__isnull=False,
                        expected_parts__isnull=False,
                    )
                    | models.Q(
                        kind=ImportRun.Kind.ARTISTS,
                        graph_revision__isnull=True,
                        membership_revision__isnull=True,
                        expected_parts__isnull=False,
                    )
                ),
                name="grow_import_review_metadata_complete",
            )
        ]
