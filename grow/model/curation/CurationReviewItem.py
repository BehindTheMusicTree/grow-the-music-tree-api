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
        UNREACHED_GENRE = "unreached_genre"
        """A regional genre that reaches neither a 'music of <place>' overview nor an accepted global root through
        its parents: the admin adds a classification edge, accepts it in `global_roots` or prunes it."""
        SYNTHETIC_OVERVIEW_SUPERSEDED = "synthetic_overview_superseded"
        """A generated `LOCAL:region-*` overview is kept although Wikidata now has an overview for its region
        (`target_item_id`): the admin chooses a `synthetic_overview_resolutions` entry."""
        SYNTHETIC_OVERVIEW_ORPHANED = "synthetic_overview_orphaned"
        """A generated overview is kept although its region no longer has any genre."""
        SYNTHETIC_OVERVIEW_RENAMED = "synthetic_overview_renamed"
        """A generated overview is kept under its former name; `target_item_id` is the new item, if any."""
        GENRE_NOT_IN_GRAPH = "genre_not_in_graph"
        """A genre grow holds with no node in the reference graph (a `LOCAL:` genre Gold stopped emitting) is kept by
        the import; `item_id` is its `wikidata_id` (empty if none) and `evidence` its uuid, kept parent and songs."""
        CLASSIFICATION_CARDINALITY = "classification_cardinality"
        """A genre of the imported graph with too many lineage parents: a global genre has at most one (none for a
        global root) and a regional genre at most one global parent. Reported, never rejected."""

        ALIAS_TARGET_MISSING = "alias_target_missing"
        ALIAS_TARGET_INELIGIBLE = "alias_target_ineligible"
        ALIAS_SOURCE_AUTO_RESOLVED = "alias_source_auto_resolved"

    GENRE_ALIAS_REASONS = (
        Reason.ALIAS_TARGET_MISSING,
        Reason.ALIAS_TARGET_INELIGIBLE,
        Reason.ALIAS_SOURCE_AUTO_RESOLVED,
    )
    GRAPH_REASONS = (Reason.GENRE_NOT_IN_GRAPH, Reason.CLASSIFICATION_CARDINALITY)
    """Alerts grow computes when it imports the reference graph; the pipeline's reports neither send nor clear them."""
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
                    & (
                        models.Q(reason__startswith="synthetic_overview_")
                        | models.Q(reason__in=["genre_not_in_graph", "classification_cardinality"])
                    )
                ),
                name="curation_review_item_rule_xor_list_key",
            )
        ]
