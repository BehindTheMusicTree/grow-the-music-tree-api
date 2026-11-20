from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from django.db.models import CharField, F, IntegerField, UUIDField, Value
from rest_framework.exceptions import ValidationError
from the_music_tree_genre_kit.criteria.selection.coverage import CriteriaCoverage
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAccess, GenreGraphDataset

from grow.genre_graph.service import DATASET_KEY, GraphValidationError
from grow.model.criteria.children.genre.Genre import Genre


class SubgenreScope(StrEnum):
    CANONICAL = "canonical"
    REGIONAL = "regional"
    ALL = "all"


def scopes_of(canonical_state: str | None) -> tuple[SubgenreScope, ...]:
    """Selection scopes the kit exposes for a node: only canonical nodes split by scope."""
    if canonical_state == "canonical":
        return SubgenreScope.CANONICAL, SubgenreScope.REGIONAL, SubgenreScope.ALL
    return (SubgenreScope.ALL,)


@dataclass(frozen=True)
class GraphClosure:
    """Reference graph closure for one graph state, keyed by genre uuid; shared across requests, never mutate.

    ``selections`` is the kit's ``GenreGraphAccess`` (ancestor, scope, descendant) projected onto genres,
    so a selection is the same set the kit's SQL selections read. ``ancestors`` is its reverse for the
    ``all`` scope.
    """

    token: tuple[UUID, UUID]
    tree_names: Mapping[UUID, str]
    selections: Mapping[UUID, Mapping[SubgenreScope, frozenset[UUID]]]
    ancestors: Mapping[UUID, frozenset[UUID]]
    playlists: Mapping[UUID, UUID]

    def ancestors_of(self, genres) -> set[UUID]:
        result = set()
        for genre in genres:
            result |= self.ancestors.get(genre, {genre})
        return result


_closure: GraphClosure | None = None

# Column layout shared by UNIONed sources: (kind, uuid_a, uuid_b, text, int_a, int_b, uuid_c).
UNION_COLUMNS = {
    "u_a": UUIDField(),
    "u_b": UUIDField(),
    "u_text": CharField(),
    "u_int_a": IntegerField(),
    "u_int_b": IntegerField(),
    "u_c": UUIDField(),
}
DATASET_ROW, GENRE_ROW, ACCESS_ROW = range(3)
FIRST_FREE_KIND = 3


def cached_closure() -> GraphClosure | None:
    return _closure


def union_source(queryset, kind, **columns):
    """Project a queryset on the shared column layout; unnamed columns are typed NULLs."""
    annotations = {"u_kind": Value(kind, output_field=IntegerField())}
    for name, field in UNION_COLUMNS.items():
        annotations[name] = F(columns[name]) if name in columns else Value(None, output_field=field)
    return queryset.order_by().annotate(**annotations).values_list("u_kind", *UNION_COLUMNS)


def graph_union_sources() -> list:
    """Dataset token, genre rows and access rows as UNION sources, in one statement with any other source.

    When a closure is cached for the token this statement sees, its graph rows are left out of the result.
    """
    sources = [
        union_source(
            GenreGraphDataset.objects.filter(pk=DATASET_KEY), DATASET_ROW, u_a="revision", u_b="membership_revision"
        )
    ]
    genre_rows = Genre.objects.filter(
        user__isnull=True, graph_node__dataset_id=DATASET_KEY, graph_node__is_active=True
    ).annotate(
        node_id=F("graph_node_id"), node_state=F("graph_node__canonical_state"), u_playlist=F("criteria_playlist__uuid")
    )
    access_rows = GenreGraphAccess.objects.filter(dataset_id=DATASET_KEY)
    cached = _closure
    if cached is not None:
        revision, membership_revision = cached.token
        genre_rows = genre_rows.exclude(
            graph_node__dataset__revision=revision, graph_node__dataset__membership_revision=membership_revision
        )
        access_rows = access_rows.exclude(dataset__revision=revision, dataset__membership_revision=membership_revision)
    sources.append(
        union_source(genre_rows, GENRE_ROW, u_a="pk", u_b="u_playlist", u_text="node_state", u_int_a="node_id")
    )
    sources.append(
        union_source(access_rows, ACCESS_ROW, u_text="scope", u_int_a="ancestor_id", u_int_b="descendant_id")
    )
    return sources


class GraphRowsReader:
    """Collects the rows of ``graph_union_sources`` from a UNION result; ``add`` ignores other kinds."""

    def __init__(self):
        self.cached = _closure
        self.token = None
        self.genres = []
        self.access = []

    def add(self, kind, a, b, text, int_a, int_b) -> bool:
        if kind == DATASET_ROW:
            self.token = (a, b)
        elif kind == GENRE_ROW:
            self.genres.append((a, int_a, text, b))
        elif kind == ACCESS_ROW:
            self.access.append((int_a, int_b, text))
        else:
            return False
        return True

    def closure(self) -> GraphClosure:
        if self.token is None:
            raise GraphValidationError("Import the reference graph with an explicit identity mapping first")
        if self.cached is not None and self.cached.token == self.token:
            return self.cached
        return closure_from_rows(self.token, self.genres, self.access)


def graph_closure() -> GraphClosure:
    """The closure of the reference graph, rebuilt only when ``revision`` or ``membership_revision`` changes.

    One statement reads the token and, only when the cached closure is stale, the graph rows. Call it inside
    the response's ``graph_read_snapshot`` so the closure and the other reads share a snapshot.
    """
    reader = GraphRowsReader()
    sources = graph_union_sources()
    for kind, a, b, text, int_a, int_b, _ in sources[0].union(*sources[1:], all=True):
        reader.add(kind, a, b, text, int_a, int_b)
    return reader.closure()


def closure_from_rows(token: tuple[UUID, UUID], rows, access_rows) -> GraphClosure:
    """Build and cache the closure from ``(genre, node, canonical_state, playlist)`` and access rows."""
    global _closure
    genre_of = {node_id: pk for pk, node_id, _, _ in rows}
    tree_names = {pk: "canonical" if state == "canonical" else "regional" for pk, _, state, _ in rows}
    members: dict[UUID, dict[str, set[UUID]]] = {pk: defaultdict(set) for pk in tree_names}
    ancestors: dict[UUID, set[UUID]] = {pk: {pk} for pk in tree_names}
    for ancestor_id, descendant_id, scope in access_rows:
        ancestor, descendant = genre_of.get(ancestor_id), genre_of.get(descendant_id)
        if ancestor is None or descendant is None:
            continue
        members[ancestor][scope].add(descendant)
        if scope == SubgenreScope.ALL:
            ancestors[descendant].add(ancestor)
    selections = {}
    for pk, by_scope in members.items():
        selection = {}
        for scope in scopes_of("canonical" if tree_names[pk] == "canonical" else None):
            # A node always selects itself, whichever scope the kit stored.
            selection[scope] = frozenset(by_scope.get(scope, ()) | {pk})
        selections[pk] = MappingProxyType(selection)
    closure = GraphClosure(
        token,
        MappingProxyType(tree_names),
        MappingProxyType(selections),
        MappingProxyType({pk: frozenset(nodes) for pk, nodes in ancestors.items()}),
        MappingProxyType({pk: playlist for pk, _, _, playlist in rows if playlist is not None}),
    )
    _closure = closure
    return closure


def clear_closure_cache() -> None:
    global _closure
    _closure = None


def parse_subgenres(value, coverage, canonical_state):
    """The selection scope requested for a node; regional nodes only select ``all``."""
    if coverage == CriteriaCoverage.ONLY:
        if value is not None:
            raise ValidationError({"subgenres": "Subgenre scope requires inclusive coverage."})
        return None
    allowed = scopes_of(canonical_state)
    try:
        scope = SubgenreScope(value) if value is not None else allowed[0]
    except ValueError:
        raise ValidationError({"subgenres": "Invalid subgenre scope."}) from None
    if scope not in allowed:
        raise ValidationError({"subgenres": "Regional genres require the all scope."})
    return scope
