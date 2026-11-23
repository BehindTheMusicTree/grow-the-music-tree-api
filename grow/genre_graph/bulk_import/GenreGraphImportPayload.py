from django.db import models


class GenreGraphImportPayload(models.Model):
    """The validated body of one reference-graph import run (a few MB of JSON), read by its merge and dropped with it."""

    run_id = models.BigIntegerField(unique=True)
    payload = models.JSONField()

    class Meta:
        db_table = "grow_genre_graph_import_payload"
