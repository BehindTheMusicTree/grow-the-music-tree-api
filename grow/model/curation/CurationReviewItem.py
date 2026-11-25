from django.db import models
from the_music_tree_grow_contracts.curation_lists import CURATION_LISTS, ITEM_ID_COLUMNS, KEY_MAX_LENGTH


class CurationReviewItem(models.Model):
    """Review items from Wikidata resolution, region-map merges, or Gold genre matching."""

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
        UNREACHED_GENRE = "unreached_genre"
        """A regional genre that reaches neither a 'music of <place>' overview nor an accepted canonical root through
        its parents: the admin adds a `regional_memberships` rule, accepts it in `canonical_roots` or prunes it."""
        SYNTHETIC_OVERVIEW_SUPERSEDED = "synthetic_overview_superseded"
        """A generated `LOCAL:region-*` overview is kept although Wikidata now has an overview for its region
        (`target_item_id`): the admin chooses a `synthetic_overview_resolutions` entry."""
        SYNTHETIC_OVERVIEW_ORPHANED = "synthetic_overview_orphaned"
        """A generated overview is kept although its region no longer has any genre."""
        SYNTHETIC_OVERVIEW_RENAMED = "synthetic_overview_renamed"
        """A generated overview is kept under its former name; `target_item_id` is the new item, if any."""

        ALIAS_TARGET_MISSING = "alias_target_missing"
        ALIAS_TARGET_INELIGIBLE = "alias_target_ineligible"
        ALIAS_SOURCE_AUTO_RESOLVED = "alias_source_auto_resolved"

    GENRE_ALIAS_REASONS = (
        Reason.ALIAS_TARGET_MISSING,
        Reason.ALIAS_TARGET_INELIGIBLE,
        Reason.ALIAS_SOURCE_AUTO_RESOLVED,
    )
    SYNTHETIC_OVERVIEW_REASONS = (
        Reason.SYNTHETIC_OVERVIEW_SUPERSEDED,
        Reason.SYNTHETIC_OVERVIEW_ORPHANED,
        Reason.SYNTHETIC_OVERVIEW_RENAMED,
    )

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
                | (models.Q(rule__isnull=True) & models.Q(list_name__isnull=False) & models.Q(key__isnull=False))
                | (
                    models.Q(rule__isnull=True)
                    & models.Q(list_name__isnull=True)
                    & models.Q(key__isnull=True)
                    & models.Q(reason__startswith="synthetic_overview_")
                ),
                name="curation_review_item_rule_xor_list_key",
            )
        ]
