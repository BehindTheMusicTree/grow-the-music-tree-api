from django.db import models


class ImportRun(models.Model):
    """One data import by the nightly pipeline, for the admin freshness page. Admin manual imports aren't recorded."""

    class Kind(models.TextChoices):
        CANONICAL_TREE = "canonical_tree"
        REGIONAL_TREE = "regional_tree"
        SONGS = "songs"
        UNRESOLVED_GENRE_TAGS = "unresolved_genre_tags"

    kind = models.TextField(choices=Kind.choices)
    imported_on = models.DateTimeField(auto_now_add=True)
    count = models.PositiveIntegerField()
    skipped_count = models.PositiveIntegerField(null=True)

    class Meta:
        db_table = "grow_import_run"
        indexes = [models.Index(fields=["kind", "-imported_on"], name="grow_import_run_kind_idx")]
