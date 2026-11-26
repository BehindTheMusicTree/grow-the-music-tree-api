"""A `LOCAL:` genre held by grow (a canonical `Genre` row with no Gold node of its own) stays in the reference graph
only while its curation rules still declare and place it: an `canonical_parent_additions` entry, plus a
`canonical_parent` edge with a parent or a `canonical_roots` entry. These guards refuse the writes that would drop
one of them while the genre exists, so the import never meets a held genre Gold stopped emitting."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from grow.curation.rule_set import Violation
    from grow.model.curation.GenreEdgeRule import GenreEdgeRule

GENERATED_OVERVIEW_PREFIX = "LOCAL:region-"
ADDITIONS = "canonical_parent_additions"
ROOTS = "canonical_roots"

EntryKeys = dict[str, set[str]]


@dataclass(frozen=True)
class HeldGenre:
    pk: UUID
    uuid: UUID
    name: str


def is_declared_local_item(item_id: str) -> bool:
    """A `LOCAL:` id a curator owns, not a generated regional overview."""
    return item_id.startswith("LOCAL:") and not item_id.startswith(GENERATED_OVERVIEW_PREFIX)


def held_local_genres(item_ids: Iterable[str] | None = None) -> dict[str, HeldGenre]:
    """The canonical `LOCAL:` genres by item id, generated regional overviews excluded."""
    from grow.model.criteria.children.genre.Genre import Genre

    genres = Genre.objects.filter(user__isnull=True, wikidata_id__startswith="LOCAL:").exclude(
        wikidata_id__startswith=GENERATED_OVERVIEW_PREFIX
    )
    if item_ids is not None:
        genres = genres.filter(wikidata_id__in=set(item_ids))
    return {
        wikidata_id: HeldGenre(pk, pk, name)
        for pk, wikidata_id, name in genres.values_list("pk", "wikidata_id", "_name")
    }


def stored_entry_keys(exclude_pk: Any = None) -> EntryKeys:
    """The canonical additions and accepted roots as stored, minus the entry at `exclude_pk`."""
    from grow.model.curation.CurationEntry import CurationEntry

    entries = CurationEntry.objects.filter(user=None, list_name__in=(ADDITIONS, ROOTS)).exclude(pk=exclude_pk)
    keys: EntryKeys = {ADDITIONS: set(), ROOTS: set()}
    for list_name, key in entries.values_list("list_name", "key"):
        keys[list_name].add(key)
    return keys


def placed_items(keys: EntryKeys, edges: Iterable[GenreEdgeRule]) -> set[str]:
    """The items with a canonical parent edge carrying a parent, or an accepted root entry."""
    from grow.model.curation.GenreEdgeRule import GenreEdgeRule

    parented = {e.item_id for e in edges if e.relation == GenreEdgeRule.Relation.CANONICAL_PARENT and e.parent_item_id}
    return parented | keys[ROOTS]


def find_local_genre_violations(
    keys: EntryKeys, edges: Iterable[GenreEdgeRule], held: dict[str, HeldGenre]
) -> list[Violation]:
    """Held genres whose curation no longer declares (`local_genre_undeclared`) or places (`local_genre_unplaced`)
    them."""
    from grow.curation.rule_set import Violation

    placed = placed_items(keys, edges)
    violations = []
    for item_id, genre in sorted(held.items()):
        label = f"{genre.name} ({item_id}, genre {genre.uuid})"
        if item_id not in keys[ADDITIONS]:
            violations.append(
                Violation(
                    "local_genre_undeclared",
                    f"{label} exists but would have no {ADDITIONS} entry: delete the genre "
                    "(this removes its rules) or alias it",
                    frozenset({item_id}),
                )
            )
        elif item_id not in placed:
            violations.append(
                Violation(
                    "local_genre_unplaced",
                    f"{label} exists but would have neither a canonical parent nor a {ROOTS} entry: delete the genre "
                    "(this removes its rules) or alias it",
                    frozenset({item_id}),
                )
            )
    return violations


def find_local_genre_removal_error(keys: EntryKeys, edges: Iterable[GenreEdgeRule], items: Iterable[str]) -> str | None:
    """Why the candidate state (`keys` and `edges` after a write) would orphan a `LOCAL:` item among `items`, if it
    would: the held genre, or the bare addition no rule places."""
    from grow.curation.rule_set import find_unplaced_local_additions, involving

    items = {i for i in items if is_declared_local_item(i)}
    if not items:
        return None
    edges = list(edges)
    violations = find_local_genre_violations(keys, edges, held_local_genres(items))
    violations += find_unplaced_local_additions(keys[ADDITIONS], keys[ROOTS], edges)
    violations = involving(violations, items)
    return violations[0].message if violations else None
