from typing import Any

from django.conf import settings
from django.db import models
from the_music_tree_api_kit.private_unique_resource.PrivateUniqueResource import PrivateUniqueResource

from grow.curation.lists import CURATION_LISTS, KEY_MAX_LENGTH
from grow.curation.rows import to_csv_row, to_row

from .CurationEntryManager import CurationEntryManager


class CurationEntry(PrivateUniqueResource):
    """
    One row of a pipeline curation list (`grow.curation.lists`). `key` is the list's key column value, or its key
    columns tab-joined for a composite key; `values` holds the other non-reason columns.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(class)ss", null=True, blank=True
    )
    list_name = models.CharField(max_length=64, choices=[(name, name) for name in CURATION_LISTS])
    key = models.CharField(max_length=KEY_MAX_LENGTH)
    values = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")

    objects: CurationEntryManager = CurationEntryManager()

    class Meta:
        db_table = "grow_curation_entry"
        constraints = [models.UniqueConstraint(fields=["list_name", "key"], name="curation_entry_list_name_key_unique")]

    @property
    def row(self) -> dict[str, Any]:
        return to_row(self.list_name, self.key, self.values, self.reason)

    @property
    def csv_row(self) -> dict[str, str]:
        return to_csv_row(self.list_name, self.key, self.values, self.reason)

    def __str__(self) -> str:
        return f"{self.list_name} | {self.key}"
