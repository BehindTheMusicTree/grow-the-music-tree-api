from dataclasses import dataclass
from typing import Literal

ITEM_ID_PATTERN = r"Q[0-9]+|LOCAL:[a-z0-9-]+"
"""A Wikidata QID, or a pipeline-synthesized `LOCAL:<slug>` id for an item Wikidata lacks."""

ITEM_ID_COLUMNS = frozenset({"item_id", "parent_item_id", "overview_item_id", "parent_id"})
BOOL_COLUMNS = frozenset({"exclude_other_parents"})
REASON_COLUMN = "reason"
KEY_MAX_LENGTH = 512
"""`CurationEntry.key` column length: a longer (joined) key is a validation error, not a database one."""


Source = Literal["wikidata", "musicbrainz", "gold"]
"""The pipeline consuming the list."""


@dataclass(frozen=True)
class CurationList:
    source: Source
    key: tuple[str, ...]
    columns: tuple[str, ...]
    """Exact CSV header order."""
    description: str

    @property
    def value_columns(self) -> tuple[str, ...]:
        return tuple(c for c in self.columns if c not in self.key and c != REASON_COLUMN)

    @property
    def has_reason(self) -> bool:
        return REASON_COLUMN in self.columns


def _item_list(description: str, *extra: str, source: Source = "wikidata") -> CurationList:
    return CurationList(source, ("item_id",), ("item_id", "item_label", "reason", *extra), description)


CURATION_LISTS: dict[str, CurationList] = {
    "accepted_canonical_roots": CurationList(
        "wikidata",
        ("item_id",),
        ("item_id", "item_label"),
        "Canonical roots reviewed and accepted as roots; any other root is flagged for review.",
    ),
    "canonical_parent_additions": _item_list("Synthetic canonical parent items the pipeline adds to the tree."),
    "capitalized_words": CurationList(
        "wikidata",
        ("word",),
        ("word", "capitalized", "reason"),
        "Words kept capitalized when sentence-casing display labels.",
    ),
    "duplicate_genres": _item_list("Wikidata duplicates of another item sharing the same name, dropped."),
    "indigenous_to_exclusions": _item_list("Items whose `indigenous to` claim is ignored for regional classification."),
    "label_overrides": CurationList(
        "wikidata",
        ("item_id",),
        ("item_id", "display_label", "reason"),
        "Explicit display label for an item, overriding sentence-casing.",
    ),
    "main_parent": _item_list(
        "Forced main parent of an item, optionally dropping its other parents.",
        "parent_item_id",
        "exclude_other_parents",
    ),
    "out_of_scope_genres": _item_list("Items that aren't a music genre at all (Wikidata misclassification), pruned."),
    "overview_reclassifications": _item_list("Genre items reclassified as regional overview items."),
    "regional_overrides": _item_list(
        "Maps a regionally specific genre to its `music of <place>` overview item.",
        "overview_item_id",
        "exclude_other_parents",
    ),
    "regional_overview_additions": _item_list("Synthetic regional overview items the pipeline adds."),
    "technique_genres": _item_list("Compositional or performance techniques, not genres, pruned."),
    "theme_genres": _item_list("Items organized around a subject, theme or subculture rather than a sound, pruned."),
    "umbrella_canonical_genres": _item_list("Genuine genres too broad to keep as canonical nodes, dropped."),
    "accepted_non_genre_tags": CurationList(
        "gold",
        ("musicbrainz_genre_name",),
        ("musicbrainz_genre_name", "reason"),
        "MusicBrainz genre tags that are permanent non-genre noise, accepted as unmatched.",
    ),
    "canonical_genre_pop_side": CurationList(
        "gold",
        ("root_genre_name", "pop_child_genre_name"),
        ("root_genre_name", "pop_child_genre_name", "reason"),
        "Direct children of a canonical root exported on its pop side.",
    ),
    "genre_alias": CurationList(
        "gold",
        ("musicbrainz_genre_name",),
        ("musicbrainz_genre_name", "wikidata_genre_name", "reason"),
        "MusicBrainz genre names matched to a differently named Wikidata genre.",
    ),
    "regional_secondary_parents": CurationList(
        "gold",
        ("item_id", "parent_id"),
        ("item_id", "item_label", "parent_id", "parent_label", "reason"),
        "Extra parent edges of a regional item exported as secondary rather than primary parents.",
    ),
    "genre_precedence": CurationList(
        "musicbrainz",
        ("musicbrainz_genre_name", "over_musicbrainz_genre_name"),
        ("musicbrainz_genre_name", "over_musicbrainz_genre_name", "reason"),
        "On a recording carrying both MusicBrainz genres, the more precise first one wins over the second.",
    ),
}

GENRE_PAIR_LISTS = frozenset({"genre_precedence"})
"""Lists keyed by two distinct MusicBrainz `genre.name`s, which MusicBrainz stores lowercase and trimmed. The first
wins over the second, so the pipeline fails on a cycle of such rules."""

EXCLUDED_GENRE_LISTS = {
    "theme": "theme_genres",
    "technique": "technique_genres",
    "out_of_scope": "out_of_scope_genres",
    "duplicate": "duplicate_genres",
}
"""Admin genre-exclusion category -> the pruning list recording it."""

EXCLUSIVE_LISTS = frozenset(EXCLUDED_GENRE_LISTS.values())
"""An item_id may sit in at most one of these lists: each prunes it for a different reason."""

PARENT_RULE_COLUMNS = {"main_parent": "parent_item_id", "regional_overrides": "overview_item_id"}
"""Lists moving an item under another: the pipeline fails on such a rule once either item is pruned."""
