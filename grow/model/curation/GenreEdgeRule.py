from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from the_music_tree_api_kit.private_unique_resource.PrivateUniqueResource import PrivateUniqueResource

from grow.curation.lists import KEY_MAX_LENGTH

from .GenreEdgeRuleManager import GenreEdgeRuleManager

PRIMARY_RELATIONS = ("canonical_parent", "regional_genre_parent")


class GenreEdgeRule(PrivateUniqueResource):
    """One curated edge between two genre items (Wikidata QIDs or `LOCAL:` ids), read by the pipeline.

    Replaces the `canonical_parent`, `accepted_canonical_roots`, `regional_genre_parent`, `regional_overviews` and
    `secondary_parents` curation lists. A null `parent_item_id` is an accepted canonical root."""

    class Relation(models.TextChoices):
        CANONICAL_PARENT = "canonical_parent"
        REGIONAL_GENRE_PARENT = "regional_genre_parent"
        REGIONAL_OVERVIEW = "regional_overview"
        SECONDARY_PARENT = "secondary_parent"

    class Action(models.TextChoices):
        ADD = "add"
        REMOVE = "remove"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(class)ss", null=True, blank=True
    )
    relation = models.CharField(max_length=32, choices=Relation.choices)
    item_id = models.CharField(max_length=KEY_MAX_LENGTH)
    parent_item_id = models.CharField(max_length=KEY_MAX_LENGTH, null=True, blank=True)
    action = models.CharField(max_length=8, choices=Action.choices, null=True, blank=True)
    exclude_other_parents = models.BooleanField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")

    objects: GenreEdgeRuleManager = GenreEdgeRuleManager()

    class Meta:
        db_table = "grow_genre_edge_rule"
        constraints = [
            models.UniqueConstraint(
                fields=["item_id", "relation"],
                condition=Q(relation__in=PRIMARY_RELATIONS),
                name="genre_edge_rule_primary_unique",
                violation_error_message="This item already has a rule of this relation",
            ),
            models.UniqueConstraint(
                fields=["item_id", "parent_item_id"],
                condition=Q(parent_item_id__isnull=False),
                name="genre_edge_rule_pair_unique",
                violation_error_message="A rule already exists for this item and parent",
            ),
            models.CheckConstraint(
                condition=~Q(item_id=F("parent_item_id")),
                name="genre_edge_rule_no_self_edge",
                violation_error_message="An item can't be its own parent",
            ),
            models.CheckConstraint(
                condition=Q(parent_item_id__isnull=False) | Q(relation="canonical_parent"),
                name="genre_edge_rule_root_is_canonical",
                violation_error_message="Only a canonical_parent rule can be a root (no parent)",
            ),
            models.CheckConstraint(
                condition=Q(parent_item_id__isnull=False) | Q(exclude_other_parents=True),
                name="genre_edge_rule_root_excludes_parents",
                violation_error_message="A root must exclude other parents",
            ),
            models.CheckConstraint(
                condition=(Q(relation="secondary_parent") & Q(action__isnull=False))
                | (~Q(relation="secondary_parent") & Q(action__isnull=True)),
                name="genre_edge_rule_action_iff_secondary",
                violation_error_message="Only a secondary_parent rule has an action, and it must",
            ),
            models.CheckConstraint(
                condition=(Q(relation="secondary_parent") & Q(exclude_other_parents__isnull=True))
                | (~Q(relation="secondary_parent") & Q(exclude_other_parents__isnull=False)),
                name="genre_edge_rule_exclude_iff_not_secondary",
                violation_error_message="exclude_other_parents is set on every relation but secondary_parent",
            ),
        ]

    @property
    def row(self) -> dict[str, Any]:
        return {
            "id": str(self.uuid),
            "relation": self.relation,
            "item_id": self.item_id,
            "parent_item_id": self.parent_item_id,
            "action": self.action,
            "exclude_other_parents": self.exclude_other_parents,
            "reason": self.reason,
        }

    def __str__(self) -> str:
        return f"{self.relation} | {self.item_id} -> {self.parent_item_id}"
