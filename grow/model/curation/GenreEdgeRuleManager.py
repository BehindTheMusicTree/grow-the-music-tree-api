import json
from typing import TYPE_CHECKING, Any, Literal

from django.db import transaction
from the_music_tree_api_kit.public_standard_resource.StandardResourceManager import StandardResourceManager
from the_music_tree_grow_contracts.curation_lists import EDGE_COLUMNS

from grow.curation.rows import InvalidRow, lock_writes
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry

if TYPE_CHECKING:
    from .GenreEdgeRule import GenreEdgeRule

AUTO_FIELDS = ["created_on", "updated_on"]
UpsertResult = Literal["created", "updated", "unchanged"]


class GenreEdgeRuleManager(StandardResourceManager):
    model: GenreEdgeRule

    def get_default_ordering(self) -> list[str]:
        return ["item_id", "relation", "target_item_id"]

    @staticmethod
    def _snapshot(instance: GenreEdgeRule) -> str:
        return json.dumps({field: getattr(instance, field) for field in EDGE_COLUMNS})

    @staticmethod
    def _validate(instance: GenreEdgeRule) -> None:
        instance.full_clean(exclude=AUTO_FIELDS, validate_unique=False)

    @staticmethod
    def _check_rule_set(relation: str, item_id: str, target_item_id: str, action: str, exclude_pk: Any = None) -> None:
        from grow.curation.edges import find_edge_candidate_error

        error = find_edge_candidate_error(relation, item_id, target_item_id, action, exclude_pk)
        if error:
            raise InvalidRow({error[0]: error[1]})

    def _lock(self) -> None:
        lock_writes(self.all())

    @transaction.atomic
    def create(self, actor: Any = None, **kwargs) -> GenreEdgeRule:
        self._lock()
        if not kwargs.get("decision_id"):
            kwargs.pop("decision_id", None)
        self._validate(self.model(**kwargs))
        self._check_rule_set(kwargs["relation"], kwargs["item_id"], kwargs["target_item_id"], kwargs["action"])
        instance = super().create(**kwargs)
        HistoryEntry.objects.record(
            instance, action=HistoryAction.CREATED, actor=actor, new_value=self._snapshot(instance)
        )
        return instance

    @transaction.atomic
    def update_instance(self, instance: GenreEdgeRule, actor: Any = None, **kwargs) -> GenreEdgeRule:
        self._lock()
        if not kwargs.get("decision_id"):
            kwargs.pop("decision_id", None)
        old_value = self._snapshot(instance)
        candidate = self.model(pk=instance.pk, **{f: getattr(instance, f) for f in EDGE_COLUMNS} | kwargs)
        candidate.user_id = instance.user_id
        candidate._state.adding = False  # so unique constraints ignore the row being updated
        candidate.full_clean(exclude=AUTO_FIELDS, validate_unique=False)
        self._check_rule_set(
            candidate.relation, candidate.item_id, candidate.target_item_id, candidate.action, instance.pk
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
        target_item_id: str,
        *,
        action: str,
        reason: str = "",
        actor: Any = None,
        decision_id: str | None = None,
    ) -> UpsertResult:
        """Makes `action` the canonical rule on the `(item_id, relation, target_item_id)` triplet, recording history.
        An existing rule keeps its `decision_id` unless one is given. Raises `ValidationError`."""
        self._lock()
        fields = {"action": action, "reason": reason}
        if decision_id:
            fields["decision_id"] = decision_id
        triplet = {"relation": relation, "item_id": item_id, "target_item_id": target_item_id}
        existing = self.filter(user=None, **triplet).first()
        if existing is None:
            self.create(actor=actor, user=None, **triplet, **fields)
            return "created"
        if all(getattr(existing, k) == v for k, v in fields.items()):
            return "unchanged"
        self.update_instance(existing, actor=actor, **fields)
        return "updated"
