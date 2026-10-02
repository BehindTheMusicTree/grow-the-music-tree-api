import json
from typing import TYPE_CHECKING, Any

from django.db import transaction
from the_music_tree_api_kit.public_standard_resource.StandardResourceManager import StandardResourceManager

from grow.curation.rows import UpsertResult, check_upsert
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry

if TYPE_CHECKING:
    from .CurationEntry import CurationEntry


class CurationEntryManager(StandardResourceManager):
    model: CurationEntry

    def get_default_ordering(self) -> list[str]:
        return ["key"]

    @staticmethod
    def _snapshot(instance: CurationEntry) -> str:
        return json.dumps({"list_name": instance.list_name, **instance.row})

    @staticmethod
    def snapshot_fragment(column: str, value: str) -> str:
        """Text of a history snapshot holding `column: value`, to filter history without parsing JSON."""
        return json.dumps({column: value})[1:-1]

    @transaction.atomic
    def create(self, actor: Any = None, **kwargs) -> CurationEntry:
        instance = super().create(**kwargs)
        HistoryEntry.objects.record(
            instance, action=HistoryAction.CREATED, actor=actor, new_value=self._snapshot(instance)
        )
        return instance

    @transaction.atomic
    def update_instance(self, instance: CurationEntry, actor: Any = None, **kwargs) -> CurationEntry:
        old_value = self._snapshot(instance)
        instance = super().update_instance(instance, **kwargs)
        HistoryEntry.objects.record(
            instance,
            action=HistoryAction.UPDATED,
            actor=actor,
            old_value=old_value,
            new_value=self._snapshot(instance),
        )
        return instance

    @transaction.atomic
    def delete_instance(self, instance: CurationEntry, actor: Any = None) -> None:
        HistoryEntry.objects.record(
            instance, action=HistoryAction.DELETED, actor=actor, old_value=self._snapshot(instance)
        )
        instance.delete()

    @transaction.atomic
    def upsert(self, list_name: str, row: dict[str, Any], actor: Any = None) -> UpsertResult:
        """Creates or updates the canonical entry with `row`'s key, recording history. Raises `InvalidRow`."""
        parsed, entry = check_upsert(self.filter(user=None), list_name, row)
        fields = {"values": parsed.values, "reason": parsed.reason}
        if entry is None:
            self.create(actor=actor, user=None, list_name=list_name, key=parsed.key, **fields)
            return "created"
        if all(getattr(entry, k) == v for k, v in fields.items()):
            return "unchanged"
        self.update_instance(entry, actor=actor, **fields)
        return "updated"
