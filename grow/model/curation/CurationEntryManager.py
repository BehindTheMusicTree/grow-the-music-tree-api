import json
from typing import TYPE_CHECKING, Any

from django.db import transaction
from the_music_tree_api_kit.public_standard_resource.StandardResourceManager import StandardResourceManager

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
        return json.dumps(instance.row)

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
