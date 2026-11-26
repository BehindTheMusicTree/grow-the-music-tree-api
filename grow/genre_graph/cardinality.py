from the_music_tree_genre_graph import GenreGraph


def find_cardinality_violations(graph: GenreGraph) -> list[tuple[str, str]]:
    """(node id, message) for each genre with too many lineage parents. Memberships don't count.

    A global genre has at most one lineage parent and a regional one at most one global lineage parent. The kit
    already rejects a global root with a lineage parent, and does not check cardinality otherwise."""
    violations = []
    for node_id in sorted(graph.node_ids):
        state = graph.state(node_id)
        if state is None:
            continue
        parents = graph.parents(node_id, "lineage")
        if state == "regional":
            parents = {parent for parent in parents if graph.state(parent) == "global"}
        if len(parents) > 1:
            kind = "parents" if state == "global" else "global parents"
            violations.append((node_id, f"A {state} genre has {len(parents)} {kind}: {', '.join(sorted(parents))}"))
    return violations
