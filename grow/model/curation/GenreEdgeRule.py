from typing import Any
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from the_music_tree_api_kit.private_unique_resource.PrivateUniqueResource import PrivateUniqueResource
from the_music_tree_grow_contracts.curation_lists import EDGE_ACTIONS, EDGE_RELATIONS, KEY_MAX_LENGTH

from .GenreEdgeRuleManager import GenreEdgeRuleManager

DECISION_ID_MAX_LENGTH = 255


def new_decision_id() -> str:
    return str(uuid4())


class GenreEdgeRule(PrivateUniqueResource):
    """One curated decision on a typed edge between two genre items (Wikidata QIDs or `LOCAL:` ids), read by the
    pipeline: `assert` adds the `(item_id, relation, target_item_id)` triplet, `prohibit` keeps the sources from
    bringing it back. Deleting a rule returns the triplet to what the sources say.

    Accepted global roots are the `global_roots` curation list, not edges."""

    class Relation(models.TextChoices):
        CLASSIFICATION = "classification"
        DERIVATION = "derivation"
        INFLUENCE = "influence"

    class Action(models.TextChoices):
        ASSERT = "assert"
        PROHIBIT = "prohibit"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(class)ss", null=True, blank=True
    )
    decision_id = models.CharField(max_length=DECISION_ID_MAX_LENGTH, default=new_decision_id)
    """The decision's stable identity in the pipeline's provenance; rows folded from older lists keep theirs."""
    relation = models.CharField(max_length=32, choices=Relation.choices)
    item_id = models.CharField(max_length=KEY_MAX_LENGTH)
    target_item_id = models.CharField(max_length=KEY_MAX_LENGTH)
    action = models.CharField(max_length=8, choices=Action.choices)
    reason = models.TextField(blank=True, default="")

    objects: GenreEdgeRuleManager = GenreEdgeRuleManager()

    class Meta:
        db_table = "grow_genre_edge_rule"
        constraints = [
            models.UniqueConstraint(
                fields=["item_id", "relation", "target_item_id"],
                name="genre_edge_rule_triplet_unique",
                violation_error_message="A rule already exists for this item, relation and target",
            ),
            models.UniqueConstraint(
                fields=["decision_id"],
                name="genre_edge_rule_decision_unique",
                violation_error_message="A rule already carries this decision_id",
            ),
            models.CheckConstraint(
                condition=~Q(item_id=F("target_item_id")),
                name="genre_edge_rule_no_self_edge",
                violation_error_message="An item can't be its own parent",
            ),
            models.CheckConstraint(
                condition=Q(relation__in=EDGE_RELATIONS),
                name="genre_edge_rule_relation_valid",
                violation_error_message="Unknown relation",
            ),
            models.CheckConstraint(
                condition=Q(action__in=EDGE_ACTIONS),
                name="genre_edge_rule_action_valid",
                violation_error_message="Unknown action",
            ),
        ]

    @property
    def row(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "item_id": self.item_id,
            "relation": self.relation,
            "target_item_id": self.target_item_id,
            "action": self.action,
            "reason": self.reason,
        }

    def __str__(self) -> str:
        return f"{self.relation} {self.action} | {self.item_id} -> {self.target_item_id}"
