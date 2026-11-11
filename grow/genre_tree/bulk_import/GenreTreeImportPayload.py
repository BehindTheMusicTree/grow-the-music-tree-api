from django.db import models


class GenreTreeImportPayload(models.Model):
    """The validated trees of one genre-trees import run (a few MB of JSON), read by its merge and dropped with it."""

    run_id = models.BigIntegerField(unique=True)
    payload = models.JSONField()

    class Meta:
        db_table = "grow_genre_tree_import_payload"
