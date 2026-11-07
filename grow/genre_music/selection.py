from collections import defaultdict, deque
from collections.abc import Hashable, Iterable, Mapping
from enum import StrEnum
from functools import cache, lru_cache


class SubgenreScope(StrEnum):
    CANONICAL = "canonical"
    REGIONAL = "regional"
    ALL = "all"


def selected_genres[K: Hashable](
    genre: K,
    tree_names: Mapping[K, str],
    primary_edges: Iterable[tuple[K, K]],
    scope: SubgenreScope,
) -> set[K]:
    """Return the inclusive selection from (parent, child) edges, deduplicating paths."""
    if genre not in tree_names:
        raise ValueError("Selected genre is missing from the graph")
    if not isinstance(scope, SubgenreScope):
        raise ValueError("Invalid subgenre scope")
    tree = tree_names[genre]
    if tree not in {"canonical", "regional"}:
        raise ValueError("Invalid genre tree")
    if tree == "regional" and scope != SubgenreScope.ALL:
        raise ValueError("Regional genres require the all scope")

    children: dict[K, set[K]] = defaultdict(set)
    for parent, child in primary_edges:
        if parent not in tree_names or child not in tree_names:
            raise ValueError("Primary edge references a missing genre")
        children[parent].add(child)

    canonical = {genre}
    if tree == "canonical" and scope != SubgenreScope.REGIONAL:
        pending = deque([genre])
        while pending:
            parent = pending.popleft()
            for child in children[parent] - canonical:
                if tree_names[child] == "canonical":
                    canonical.add(child)
                    pending.append(child)
        if scope == SubgenreScope.CANONICAL:
            return canonical

    reachable = {genre}
    pending = deque([genre])
    while pending:
        parent = pending.popleft()
        for child in children[parent] - reachable:
            reachable.add(child)
            pending.append(child)
    if tree == "regional":
        return reachable
    regional = {node for node in reachable if tree_names[node] == "regional"} | {genre}
    if scope == SubgenreScope.REGIONAL:
        return regional
    return canonical | regional


def genre_graph():
    from grow.model.criteria.children.genre.Genre import Genre

    rows = list(
        Genre.objects.filter(user__isnull=True).values_list(
            "pk", "tree_name", "parent_id", "additional_primary_parents__pk"
        )
    )
    trees = {pk: tree for pk, tree, _, _ in rows}
    edges = {
        (parent, pk)
        for pk, _, direct_parent, extra_parent in rows
        for parent in (direct_parent, extra_parent)
        if parent is not None and parent in trees
    }
    return trees, edges


def parse_subgenres(value, coverage, tree_name):
    from rest_framework.exceptions import ValidationError
    from the_music_tree_genre_kit.criteria.selection.coverage import CriteriaCoverage

    if coverage == CriteriaCoverage.ONLY:
        if value is not None:
            raise ValidationError({"subgenres": "Subgenre scope requires inclusive coverage."})
        return None
    try:
        scope = (
            SubgenreScope(value)
            if value is not None
            else (SubgenreScope.CANONICAL if tree_name == "canonical" else SubgenreScope.ALL)
        )
    except ValueError:
        raise ValidationError({"subgenres": "Invalid subgenre scope."}) from None
    if tree_name == "regional" and scope != SubgenreScope.ALL:
        raise ValidationError({"subgenres": "Regional genres require the all scope."})
    return scope


@lru_cache(maxsize=1)
def _selection_index[K: Hashable](tree_items: tuple[tuple[K, str], ...], primary_edges: frozenset[tuple[K, K]]):
    # Cache only pure graph inputs: database writes and rollbacks select their own snapshot.
    tree_names = dict(tree_items)
    nodes = list(tree_names)
    indices = {node: index for index, node in enumerate(nodes)}
    children: list[set[int]] = [set() for _ in nodes]
    parents: list[set[int]] = [set() for _ in nodes]
    for parent_node, child_node in primary_edges:
        p, c = indices.get(parent_node), indices.get(child_node)
        if p is None or c is None:
            raise ValueError("Primary edge references a missing genre")
        children[p].add(c)
        parents[c].add(p)
    remaining = [len(descendants) for descendants in children]
    pending = deque(index for index, count in enumerate(remaining) if count == 0)
    reachable = [1 << index for index in range(len(nodes))]
    canonical = reachable.copy()
    canonical_nodes = [tree_names[node] == "canonical" for node in nodes]
    regional_mask = 0
    for index, node in enumerate(nodes):
        if tree_names[node] == "regional":
            regional_mask |= 1 << index
        elif tree_names[node] != "canonical":
            raise ValueError("Invalid genre tree")
    processed = 0
    while pending:
        child = pending.popleft()
        processed += 1
        for parent in parents[child]:
            reachable[parent] |= reachable[child]
            if canonical_nodes[child]:
                canonical[parent] |= canonical[child]
            remaining[parent] -= 1
            if remaining[parent] == 0:
                pending.append(parent)
    if processed != len(nodes):
        raise ValueError("Primary genre graph contains a cycle")

    @cache
    def members(mask: int) -> frozenset[K]:
        result = set()
        while mask:
            bit = mask & -mask
            result.add(nodes[bit.bit_length() - 1])
            mask ^= bit
        return frozenset(result)

    return indices, reachable, canonical, regional_mask, members


def all_genre_selections[K: Hashable](
    tree_names: Mapping[K, str], primary_edges: Iterable[tuple[K, K]], *, genres: Iterable[K] | None = None
) -> dict[K, dict[SubgenreScope, frozenset[K]]]:
    """Build distinct primary closures, materializing only the requested genres.

    Integer bitsets keep shared descendant unions cheap on the full production graph;
    the latest graph index is reused across catalogue and membership projections.
    """
    indices, reachable, canonical, regional_mask, members = _selection_index(
        tuple(tree_names.items()), frozenset(primary_edges)
    )
    result = {}
    for genre in tree_names if genres is None else genres:
        index = indices[genre]
        if tree_names[genre] == "regional":
            result[genre] = {SubgenreScope.ALL: members(reachable[index])}
        else:
            regional = (reachable[index] & regional_mask) | (1 << index)
            result[genre] = {
                SubgenreScope.CANONICAL: members(canonical[index]),
                SubgenreScope.REGIONAL: members(regional),
                SubgenreScope.ALL: members(canonical[index] | regional),
            }
    return result
