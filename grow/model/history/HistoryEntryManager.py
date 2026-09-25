from typing import Any

from django.db.models import Model
from the_music_tree_api_kit.public_standard_resource.StandardResourceManager import StandardResourceManager

from .Fields import Fields
from .HistoryAction import HistoryAction


class HistoryEntryManager(StandardResourceManager):
    def record(
        self,
        instance: Model,
        *,
        action: HistoryAction,
        actor: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
    ) -> None:
        self.create(
            user=instance.user,
            **{Fields.CONTENT: instance},
            action=action,
            actor_email=actor,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
        )
