from uuid import uuid4

from django.conf import settings
from django.db import models


class SongGenreUndo(models.Model):
    """What one `assign-genre` call overwrote, so the same admin can undo it exactly.

    `entries` holds one dict per song: its previous attributions (or legacy genre without a dataset), the assignment
    revision the action produced (the undo's concurrency guard) and the previous curation rule row, or None when the
    rule did not exist. A token is single-use: undoing deletes it."""

    token = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    entries = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grow_song_genre_undo"
