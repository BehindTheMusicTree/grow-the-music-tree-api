from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from the_music_tree_api_kit.field.foreign_key.AppForeignKey import AppForeignKey
from the_music_tree_api_kit.private_unique_resource.PrivateUniqueResource import PrivateUniqueResource

from .Fields import Fields
from .HistoryAction import HistoryAction
from .HistoryEntryManager import HistoryEntryManager


class HistoryEntry(PrivateUniqueResource):
    """Actor+timestamp+action log entry for a genre or track edit. Written by manager hooks, never by API writes."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(class)ss", null=True, blank=True
    )

    content_type = AppForeignKey(ContentType, on_delete=models.CASCADE)
    content_uuid = models.UUIDField(db_column="object_pk")
    content = GenericForeignKey(ct_field=Fields.CONTENT_TYPE, fk_field=Fields.CONTENT_UUID)  # type: ignore

    action = models.CharField(max_length=32, choices=HistoryAction.choices)
    actor_email = models.CharField(max_length=255, null=True, blank=True)
    """`None` means the pipeline import made the change, not an admin."""
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)

    objects: HistoryEntryManager = HistoryEntryManager()

    class Meta:
        db_table = "grow_history_entry"
        verbose_name = "History Entry"
        verbose_name_plural = "History Entries"
        indexes = [
            models.Index(fields=[Fields.USER, Fields.CONTENT_TYPE, Fields.CONTENT_UUID]),
        ]

    def __str__(self) -> str:
        return f"{self.uuid} | {self.content_type} | {self.content_uuid} | {self.action} | {self.actor_email}"
