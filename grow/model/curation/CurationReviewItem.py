from django.db import models

from grow.curation.lists import CURATION_LISTS, ITEM_ID_COLUMNS, KEY_MAX_LENGTH


class CurationReviewItem(models.Model):
    """A curation entry's item id the pipeline's last run couldn't resolve on Wikidata, so it dropped the rule.

    Each pipeline report replaces every item."""

    class Reason(models.TextChoices):
        REDIRECT_CONFLICT = "redirect_conflict"
        """Redirected, but remapping the entry to `target_item_id` clashes with another entry."""
        MISSING = "missing"
        """Deleted from Wikidata."""
        NOT_IN_TREE = "not_in_tree"
        """Not in the pipeline's genre tree."""
        INVALID_RULE = "invalid_rule"
        """The rule contradicts Wikidata (accepted root classed regional, parent on the wrong axis, wrong overview
        flag, ...), so the pipeline dropped it from the run. `evidence` carries the detail."""
        EXCLUSIVE_PARENT_REGIONAL = "exclusive_parent_regional"
        """A `canonical_parent` with `exclude_other_parents` whose item still ends up regional: the exclusion cannot
        hold, so the item belongs in `forced_canonical_genres`."""

    list_name = models.CharField(max_length=64, choices=[(name, name) for name in CURATION_LISTS], null=True)
    key = models.CharField(max_length=KEY_MAX_LENGTH, null=True)
    rule = models.ForeignKey("grow.GenreEdgeRule", on_delete=models.CASCADE, null=True, related_name="review_items")
    """The edge rule concerned, instead of `(list_name, key)`, for the rules that left the generic curation lists."""
    column = models.CharField(max_length=32, choices=[(c, c) for c in sorted(ITEM_ID_COLUMNS)])
    item_id = models.TextField()
    reason = models.TextField(choices=Reason.choices)
    target_item_id = models.TextField(null=True)
    evidence = models.JSONField(null=True)
    """Wikidata facts the pipeline saw when dropping the rule (label, P31/P279, ...), for the admin to act on."""
    reported_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grow_curation_review_item"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(rule__isnull=False) & models.Q(list_name__isnull=True) & models.Q(key__isnull=True))
                | (models.Q(rule__isnull=True) & models.Q(list_name__isnull=False) & models.Q(key__isnull=False)),
                name="curation_review_item_rule_xor_list_key",
            )
        ]
