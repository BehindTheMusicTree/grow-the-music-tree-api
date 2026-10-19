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

    list_name = models.CharField(max_length=64, choices=[(name, name) for name in CURATION_LISTS])
    key = models.CharField(max_length=KEY_MAX_LENGTH)
    column = models.CharField(max_length=32, choices=[(c, c) for c in sorted(ITEM_ID_COLUMNS)])
    item_id = models.TextField()
    reason = models.TextField(choices=Reason.choices)
    target_item_id = models.TextField(null=True)
    reported_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grow_curation_review_item"
