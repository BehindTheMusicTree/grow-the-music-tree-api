from dataclasses import dataclass
from typing import Literal

ADDITION_LABEL_COLUMN = "label"
GLOBAL_ROOTS_LIST = "global_roots"
RETIRED_HISTORY_LISTS = frozenset(
    {
        "expression_styles",
        "canonical_roots",
        "canonical_parent_additions",
        "canonical_genre_scene",
        "canonical_genre_pop_side",
        "forced_canonical_genres",
        "regional_memberships",
        "genre_derivations",
        "canonical_parent",
        "regional_genre_parent",
        "regional_overviews",
        "secondary_parents",
    }
)
"""Lists that no longer exist (renamed, folded into the edges, or the legacy edge projections), still readable in the
curation history."""
EDGE_RELATIONS = ("classification", "derivation", "influence")
EDGE_ACTIONS = ("assert", "prohibit")
EDGE_COLUMNS = ("decision_id", "item_id", "relation", "target_item_id", "action", "reason")
"""Columns of an exported genre edge rule, and the header order of `genre_edges.csv`."""

ITEM_ID_PATTERN = r"Q[0-9]+|LOCAL:[a-z0-9-]+"
"""A Wikidata QID, or a pipeline-synthesized `LOCAL:<slug>` id for an item Wikidata lacks."""

ITEM_ID_COLUMNS = frozenset(
    {
        "item_id",
        "overview_item_id",
        "genre_item_id",
        "over_item_id",
        "context_item_id",
        "root_item_id",
        "pop_child_item_id",
        "replacement_item_id",
        "expression_item_id",  # Kept for the history of expression_styles.
        "style_item_id",
        "source_item_id",
        "target_item_id",
    }
)
GRAPH_ITEM_ID_PATTERN = r"Q[1-9][0-9]*|LOCAL:[a-z0-9]+(?:-[a-z0-9]+)*"
"""The regional graph contract's item id (genre-kit `genre_graph.schema.json`): stricter than `ITEM_ID_PATTERN`."""
ENTITY_ID_PATTERN = r"[a-z]{4}[0-9]{4}|Q[0-9]+"
"""A Glottocode, or the QID of a Wikidata-only cultural entity."""

ENTITY_ID_COLUMNS = frozenset({"entity_id", "child_entity_id", "parent_entity_id"})
TRADITION_ID_COLUMNS = frozenset({"wikidata_id", "from_wikidata_id", "to_wikidata_id"})
"""Columns holding the QID of a Wikidata music tradition."""
QID_ENTITY_LISTS = frozenset({"entity_additions"})
"""Entity lists whose `entity_id` is always a QID: a Glottocode already comes from Glottolog."""
COLUMN_CHOICES: dict[str, dict[str, tuple[str, ...]]] = {
    "cultural_membership_overrides": {"action": ("add", "remove")},
    "federated_state_overrides": {"action": ("add", "remove")},
    "place_relation_overrides": {"extent": ("full", "partial", "reject")},
    "tradition_link_overrides": {"kind": ("lineage", "association"), "action": ("add", "remove")},
    "global_genre_scene": {"scene": ("commercial", "underground")},
    "synthetic_overview_resolutions": {"action": ("replace", "remove")},
    "regional_overview_types": {"overview_type": ("current", "historical")},
    "local_identities": {"kind": ("genre", "overview")},
    "region_overrides": {"region_id": ("americas", "europe", "africa", "asia", "oceania", "religions")},
    "entity_additions": {
        "entity_kind": ("cultural_region", "macro_region", "city", "admin_unit", "historical_country")
    },
}
"""Per list, the closed set of values of its enumerated columns."""
INT_COLUMNS = frozenset({"start_year", "end_year"})
BOOL_COLUMNS = frozenset({"is_default", "is_cultural"})
OPTIONAL_COLUMNS = frozenset(
    {
        "genre_item_id",
        "replacement_item_id",
        "entity_id",
        "entity_kind",
        "youtube_video_id",
        "unplayable_reason",
        "summary",
        *INT_COLUMNS,
    }
)
GENRE_ALIAS_LIST = "genre_alias"
GENRE_ALIAS_COLUMNS = ("musicbrainz_genre_name", "wikidata_genre_name", "target_item_id", "reason")


def is_optional_column(column: str) -> bool:
    return column in OPTIONAL_COLUMNS


REASON_COLUMN = "reason"
DECISION_ID_COLUMN = "decision_id"
PROVENANCE_COLUMNS = (DECISION_ID_COLUMN, "decision_source", REASON_COLUMN)
"""Provenance of a regional graph decision: the contract's `{decisionId, source, rationale}`, `reason` being the
rationale."""
KEY_MAX_LENGTH = 512
"""`CurationEntry.key` column length: a longer (joined) key is a validation error, not a database one."""


Source = Literal["wikidata", "musicbrainz", "gold", "geohistory"]
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

    def column_specs(self, list_name: str) -> tuple[dict[str, str | bool], ...]:
        return tuple(
            {
                "name": c,
                "kind": "item_id"
                if c in ITEM_ID_COLUMNS
                else "tradition_id"
                if c in TRADITION_ID_COLUMNS
                else "entity_id"
                if c in ENTITY_ID_COLUMNS
                else "int"
                if c in INT_COLUMNS
                else "bool"
                if c in BOOL_COLUMNS
                else "text",
                "optional": is_optional_column(c) and c not in self.key,
            }
            for c in self.columns
        )


def _item_list(description: str, *extra: str, source: Source = "wikidata") -> CurationList:
    return CurationList(source, ("item_id",), ("item_id", "reason", *extra), description)


def _addition_list(description: str) -> CurationList:
    return CurationList("wikidata", ("item_id",), ("item_id", ADDITION_LABEL_COLUMN, "reason"), description)


def _graph_list(key: tuple[str, ...], values: tuple[str, ...], description: str) -> CurationList:
    return CurationList("gold", key, (*key, *values, *PROVENANCE_COLUMNS), description)


CURATION_LISTS: dict[str, CurationList] = {
    "global_parent_additions": _addition_list("Synthetic global parent items the pipeline adds to the tree."),
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
    "forced_global_genres": _item_list(
        "Genres kept global although a parent is regional; their own regional sources are ignored."
    ),
    "out_of_scope_genres": _item_list("Items that aren't a music genre at all (Wikidata misclassification), pruned."),
    "overview_reclassifications": _item_list("Genre items reclassified as regional overview items."),
    "local_identities": _graph_list(
        ("item_id",),
        ("kind", "label"),
        "Identity of a `LOCAL:` item of the regional graph, which Wikidata lacks: a `genre` or an `overview`.",
    ),
    "global_roots": _graph_list(
        ("item_id",),
        (),
        "Genres accepted as roots of the global tree; any other root is flagged for review. The graph's "
        "`globalRoots` must equal this list.",
    ),
    "regional_anchorings": _graph_list(
        ("item_id", "overview_item_id"),
        (),
        "Regional overview an item is anchored to.",
    ),
    "genre_merges": _graph_list(
        ("source_item_id", "target_item_id"),
        (),
        "A node merged into another through the graph: the source's relations, display children and attributions "
        "move to the target and the source is retired.",
    ),
    "regional_overview_types": _graph_list(
        ("item_id",),
        ("overview_type",),
        "Whether a regional overview (Wikidata item or generated `LOCAL:` one) is `current` or `historical`, "
        "overriding the type Gold derives; an overview with neither a derived type nor an entry fails the export.",
    ),
    "regional_overview_additions": _addition_list("Synthetic regional overview items the pipeline adds."),
    "synthetic_overview_resolutions": CurationList(
        "gold",
        ("item_id",),
        ("item_id", "action", "replacement_item_id", "reason"),
        "Generated `LOCAL:region-*` overviews retired by hand: `replace` moves its children under "
        "`replacement_item_id`, `remove` drops the node. Without an entry, the pipeline keeps the overview.",
    ),
    "technique_genres": _item_list("Compositional or performance techniques, not genres, pruned."),
    "theme_genres": _item_list("Items organized around a subject, theme or subculture rather than a sound, pruned."),
    "umbrella_non_stylistic_genres": _item_list(
        "Appellations without a coherent style (e.g. French touch) or genres too broad to keep as global nodes, "
        "dropped."
    ),
    "umbrella_stylistic_genres": _item_list(
        "Global genres kept in the tree only to group sub-genres: no song is assigned to them directly.",
        source="gold",
    ),
    "global_genre_scene": CurationList(
        "gold",
        ("item_id",),
        ("item_id", "scene", "reason"),
        "Global genres the front displays as the commercial or the underground side of their parent.",
    ),
    "accepted_non_genre_tags": CurationList(
        "gold",
        ("musicbrainz_genre_name",),
        ("musicbrainz_genre_name", "reason"),
        "MusicBrainz genre tags that are permanent non-genre noise, accepted as unmatched.",
    ),
    "musicbrainz_free_genre_tags": CurationList(
        "musicbrainz",
        ("musicbrainz_tag_name",),
        ("musicbrainz_tag_name", "reason"),
        "Free MusicBrainz tags that are not official MusicBrainz genres but are kept as genre tags.",
    ),
    "global_genre_pop_side": CurationList(
        "gold",
        ("root_item_id", "pop_child_item_id"),
        ("root_item_id", "pop_child_item_id", "reason"),
        "Direct children of a global root exported on its pop side.",
    ),
    GENRE_ALIAS_LIST: CurationList(
        "gold",
        ("musicbrainz_genre_name",),
        GENRE_ALIAS_COLUMNS,
        "MusicBrainz tags matched to genres by stable identity.",
    ),
    "genre_disambiguation": CurationList(
        "gold",
        ("musicbrainz_genre_name", "item_id"),
        ("musicbrainz_genre_name", "item_id", "is_default", "reason"),
        "Candidate genres of an ambiguous MusicBrainz tag: a song gets the candidate in the lineage of one of its "
        "other genres, else the default.",
    ),
    "genre_disambiguation_context": CurationList(
        "gold",
        ("musicbrainz_genre_name", "item_id", "context_item_id"),
        ("musicbrainz_genre_name", "item_id", "context_item_id", "reason"),
        "On a song also carrying context_item_id (or a genre under it), an ambiguous tag resolves to item_id.",
    ),
    "song_genre": CurationList(
        "musicbrainz",
        ("musicbrainz_recording_id",),
        ("musicbrainz_recording_id", "genre_item_id", *PROVENANCE_COLUMNS),
        "Genre an admin assigned to a song, overriding its MusicBrainz tags.",
    ),
    "recording_youtube_video": CurationList(
        "musicbrainz",
        ("musicbrainz_recording_id",),
        ("musicbrainz_recording_id", "youtube_video_id", "unplayable_reason", "reason"),
        "YouTube video an admin set on a song, with the unplayable reason when it can't be played.",
    ),
    "essential_songs": CurationList(
        "gold",
        ("item_id", "musicbrainz_recording_id"),
        ("item_id", "musicbrainz_recording_id", "position", "reason"),
        "Songs an admin picked as essential for a genre, in order. Grow applies edits to the genre at once; Gold only checks each MBID exists.",
    ),
    "summary_overrides": CurationList(
        "gold",
        ("item_id",),
        ("item_id", "summary", "reason"),
        "Genre summary an admin wrote, overriding the Wikipedia one.",
    ),
    "genre_precedence": CurationList(
        "gold",
        ("item_id", "over_item_id"),
        ("item_id", "over_item_id", "reason"),
        "On a song carrying both genres, the first, more precise one wins over the second.",
    ),
    "entity_cultural_roles": CurationList(
        "geohistory",
        ("entity_id",),
        ("entity_id", "is_cultural", "reason"),
        "Cultural qualification independent of entity kind; administrative membership is automatic.",
    ),
    "cultural_membership_overrides": CurationList(
        "geohistory",
        ("child_entity_id", "parent_entity_id"),
        ("child_entity_id", "parent_entity_id", "action", "reason"),
        "Cultural parent or exclusion; memberships are transitive and exclusions take precedence.",
    ),
    "entity_additions": CurationList(
        "geohistory",
        ("entity_id",),
        ("entity_id", "entity_kind", "reason"),
        "Wikidata items ingested as cultural entities although no bulk class covers them; a blank `entity_kind` "
        "keeps them undrawn, `cultural_region` or `macro_region` makes them a map zone, `city` a point under its administrative unit, `admin_unit` a drawn administrative unit (a former region), "
        "`historical_country` a drawn former state (a civilization or colony outlined from a historical source).",
    ),
    "entity_exclusions": CurationList(
        "geohistory",
        ("entity_id",),
        ("entity_id", "reason"),
        "Cultural entities dropped, with their membership and succession edges.",
    ),
    "entity_membership_overrides": CurationList(
        "geohistory",
        ("child_entity_id", "parent_entity_id"),
        ("child_entity_id", "parent_entity_id", "action", "reason"),
        "Membership edges of a cultural entity: `add` adds a parent, `remove` drops one.",
    ),
    "federated_state_overrides": CurationList(
        "geohistory",
        ("entity_id",),
        ("entity_id", "action", "reason"),
        "Administrative units the region map always draws as federated states, even without a genre: `add` flags one "
        "Wikidata does not class as a federated state, `remove` unflags one it does.",
    ),
    "place_relation_overrides": CurationList(
        "geohistory",
        ("child_entity_id", "parent_entity_id"),
        ("child_entity_id", "parent_entity_id", "extent", "reason"),
        "Spatial relation between two entities, overriding the resolved extent.",
    ),
    "entity_time_span_overrides": CurationList(
        "geohistory",
        ("entity_id",),
        ("entity_id", "start_year", "end_year", "reason"),
        "Start and end year of a cultural entity (BCE negative, no year 0), overriding the sourced dates; a blank "
        "year keeps the sourced one.",
    ),
    "region_overrides": CurationList(
        "geohistory",
        ("entity_id",),
        ("entity_id", "region_id", "reason"),
        "Region of a genealogy column's entity, overriding its area-weighted continent: for transcontinental states "
        "and religions.",
    ),
    "tradition_additions": CurationList(
        "geohistory",
        ("wikidata_id",),
        ("wikidata_id", "reason"),
        "Wikidata items ingested as music traditions although no detection rule covers them.",
    ),
    "tradition_exclusions": CurationList(
        "geohistory",
        ("wikidata_id",),
        ("wikidata_id", "reason"),
        "Music traditions dropped, with their placements and links.",
    ),
    "cultural_place_overrides": CurationList(
        "geohistory",
        ("child_entity_id",),
        ("child_entity_id", "parent_entity_id", "reason"),
        "Geographic anchor for music associated with a language or ethnic group. An explicit tradition "
        "placement takes priority.",
    ),
    "tradition_placement_overrides": CurationList(
        "geohistory",
        ("wikidata_id",),
        ("wikidata_id", "entity_id", "start_year", "end_year", "reason"),
        "Cultural entity and start and end year (BCE negative, no year 0) placing a music tradition, overriding the "
        "derived ones; a blank field keeps the derived value. One row per tradition: further places go in "
        "`tradition_extra_places`.",
    ),
    "tradition_extra_places": CurationList(
        "geohistory",
        ("wikidata_id", "entity_id"),
        ("wikidata_id", "entity_id", "reason"),
        "Further places a music tradition is listed on beside its anchor (a successor state's heirs).",
    ),
    "tradition_link_overrides": CurationList(
        "geohistory",
        ("from_wikidata_id", "to_wikidata_id", "kind"),
        ("from_wikidata_id", "to_wikidata_id", "kind", "action", "reason"),
        "Links between music traditions, `lineage` or `association`: `add` adds one, `remove` drops a derived one.",
    ),
}

GRAPH_LISTS = frozenset(
    {
        "local_identities",
        "global_roots",
        "regional_anchorings",
        "genre_merges",
        "regional_overview_types",
    }
)
"""Lists carrying regional graph decisions: each has provenance, strict item ids and graph-wide checks
(grow's `curation/rule_set.py`). `local_identities` precedes the other graph lists in `CURATION_LISTS` so a CSV import declares an identity
before any row uses it."""

GRAPH_PAIR_LISTS = frozenset({"regional_anchorings", "genre_merges"})
"""Graph lists keyed by two item ids, which must differ."""

ADDITION_LISTS = frozenset({"global_parent_additions", "regional_overview_additions"})
"""Lists whose rows create a node: their `label` is the item's only name until it reaches the tree."""

ITEM_PAIR_LISTS = frozenset({"genre_precedence"})
"""Lists keyed by two distinct item ids, the first winning over the second, so the pipeline fails on a cycle of such
rules."""

EXCLUDED_GENRE_LISTS = {
    "theme": "theme_genres",
    "technique": "technique_genres",
    "out_of_scope": "out_of_scope_genres",
    "duplicate": "duplicate_genres",
}
"""Admin genre-exclusion category -> the pruning list recording it."""

EXCLUSIVE_LISTS = frozenset(EXCLUDED_GENRE_LISTS.values())
"""An item_id may sit in at most one of these lists: each prunes it for a different reason."""
