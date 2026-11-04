from uuid import uuid7

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from the_music_tree_api_kit.field.foreign_key.AppForeignKey import AppForeignKey
from the_music_tree_api_kit.private_unique_resource.PrivateUniqueResource import PrivateUniqueResource

from .Fields import Fields
from .HistoryAction import HistoryAction
from .HistoryEntryManager import HistoryEntryManager

CONTENT_INDEX = "grow_history_content_idx"


class HistoryEntry(PrivateUniqueResource):
    """Actor+timestamp+action log entry for a genre or track edit. Written by manager hooks, never by API writes."""

    # Time-ordered, like the song merge's bulk inserts: new entries append to the pkey btree instead of a random page.
    uuid = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(class)ss", null=True, blank=True
    )

    content_type = AppForeignKey(ContentType, on_delete=models.CASCADE)
    content_uuid = models.UUIDField(db_column="object_pk")
    content = GenericForeignKey(ct_field=Fields.CONTENT_TYPE, fk_field=Fields.CONTENT_UUID)  # type: ignore

    action = models.CharField(max_length=32, choices=HistoryAction.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="history_actions", null=True, blank=True
    )
    """`None` means the pipeline import made the change, not an admin."""
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)

    objects: HistoryEntryManager = HistoryEntryManager()

    class Meta:
        db_table = "grow_history_entry"
        verbose_name = "History Entry"
        verbose_name_plural = "History Entries"
        indexes = [
            # Serves an item's history (filtered on content, newest first) and the curation sync's content-type count.
            models.Index(fields=[Fields.CONTENT_TYPE, Fields.CONTENT_UUID, Fields.CREATED_ON], name=CONTENT_INDEX),
        ]

    def __str__(self) -> str:
        return f"{self.uuid} | {self.content_type} | {self.content_uuid} | {self.action} | {self.actor_id}"
