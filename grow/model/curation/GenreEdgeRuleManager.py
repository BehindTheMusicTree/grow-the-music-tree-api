import json
from typing import TYPE_CHECKING, Any, Literal

from django.db import transaction
from django.db.models import Q
from the_music_tree_api_kit.public_standard_resource.StandardResourceManager import StandardResourceManager

from grow.curation.rows import InvalidRow, lock_writes
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry

if TYPE_CHECKING:
    from .GenreEdgeRule import GenreEdgeRule

SNAPSHOT_FIELDS = ("relation", "item_id", "parent_item_id", "action", "exclude_other_parents", "reason")
AUTO_FIELDS = ["created_on", "updated_on"]
PRIMARY_RELATIONS = ("canonical_parent", "regional_genre_parent")
UpsertResult = Literal["created", "updated", "unchanged"]


class GenreEdgeRuleManager(StandardResourceManager):
    model: GenreEdgeRule

    def get_default_ordering(self) -> list[str]:
        return ["item_id", "relation", "parent_item_id"]

    @staticmethod
    def _snapshot(instance: GenreEdgeRule) -> str:
        return json.dumps({field: getattr(instance, field) for field in SNAPSHOT_FIELDS})

    @staticmethod
    def _validate(instance: GenreEdgeRule) -> None:
        instance.full_clean(exclude=AUTO_FIELDS, validate_unique=False)

    @staticmethod
    def _check_rule_set(
        relation: str, item_id: str, parent_item_id: str | None, action: str | None, exclude_pk: Any = None
    ) -> None:
        from grow.curation.edges import find_edge_candidate_error, find_edge_scene_split_error

        if relation == "canonical_parent" and parent_item_id is not None:
            error = find_edge_scene_split_error(item_id, parent_item_id, exclude_pk)
            if error:
                raise InvalidRow({"parent_item_id": error})
        candidate_error = find_edge_candidate_error(relation, item_id, parent_item_id, action, exclude_pk)
        if candidate_error:
            raise InvalidRow({candidate_error[0]: candidate_error[1]})

    def _lock(self) -> None:
        lock_writes(self.all())

    @transaction.atomic
    def create(self, actor: Any = None, **kwargs) -> GenreEdgeRule:
        self._lock()
        self._validate(self.model(**kwargs))
        self._check_rule_set(kwargs["relation"], kwargs["item_id"], kwargs.get("parent_item_id"), kwargs.get("action"))
        instance = super().create(**kwargs)
        HistoryEntry.objects.record(
            instance, action=HistoryAction.CREATED, actor=actor, new_value=self._snapshot(instance)
        )
        return instance

    @transaction.atomic
    def update_instance(self, instance: GenreEdgeRule, actor: Any = None, **kwargs) -> GenreEdgeRule:
        self._lock()
        old_value = self._snapshot(instance)
        candidate = self.model(pk=instance.pk, **{f: getattr(instance, f) for f in SNAPSHOT_FIELDS} | kwargs)
        candidate.user_id = instance.user_id
        candidate._state.adding = False  # so unique constraints ignore the row being updated
        candidate.full_clean(exclude=AUTO_FIELDS, validate_unique=False)
        self._check_rule_set(
            candidate.relation, candidate.item_id, candidate.parent_item_id, candidate.action, instance.pk
        )
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
    def delete_instance(self, instance: GenreEdgeRule, actor: Any = None) -> None:
        self._lock()
        HistoryEntry.objects.record(
            instance, action=HistoryAction.DELETED, actor=actor, old_value=self._snapshot(instance)
        )
        instance.delete()

    @transaction.atomic
    def upsert(
        self,
        relation: str,
        item_id: str,
        parent_item_id: str | None,
        *,
        action: str | None = None,
        exclude_other_parents: bool | None = None,
        reason: str = "",
        actor: Any = None,
    ) -> UpsertResult:
        """Makes `(relation, item_id, parent_item_id)` the canonical rule: replaces the rule holding the same primary
        assertion (one per item and axis) or the same pair, recording history. Raises `ValidationError`."""
        self._lock()
        fields = {
            "action": action,
            "exclude_other_parents": exclude_other_parents,
            "reason": reason,
        }
        rules = self.filter(user=None)
        occupied = Q(item_id=item_id, parent_item_id=parent_item_id) if parent_item_id is not None else Q(pk=None)
        if relation in PRIMARY_RELATIONS:
            occupied |= Q(item_id=item_id, relation=relation)
        existing = list(rules.filter(occupied))
        same = next(
            (r for r in existing if r.relation == relation and r.parent_item_id == parent_item_id),
            None,
        )
        for other in existing:
            if other is not same:
                self.delete_instance(other, actor=actor)
        if same is None:
            self.create(
                actor=actor,
                user=None,
                relation=relation,
                item_id=item_id,
                parent_item_id=parent_item_id,
                **fields,
            )
            return "created"
        if all(getattr(same, k) == v for k, v in fields.items()):
            return "unchanged"
        self.update_instance(same, actor=actor, **fields)
        return "updated"
