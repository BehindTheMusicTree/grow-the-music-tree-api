from grow.genre_graph.cardinality import find_cardinality_violations


class FakeGraph:
    def __init__(self, states, lineage):
        self._states = states
        self._lineage = lineage
        self.node_ids = set(states)

    def state(self, node_id):
        return self._states[node_id]

    def parents(self, node_id, kind):
        assert kind == "lineage"
        return set(self._lineage.get(node_id, ()))


def test_one_parent_each_then_no_violation():
    graph = FakeGraph({"g": "global", "r": "regional"}, {"r": {"g"}})

    assert find_cardinality_violations(graph) == []


def test_global_genre_with_two_parents_then_violation():
    graph = FakeGraph({"a": "global", "b": "global", "c": "global"}, {"c": {"a", "b"}})

    [(node_id, message)] = find_cardinality_violations(graph)

    assert node_id == "c"
    assert "2 parents: a, b" in message


def test_regional_genre_counts_only_global_parents():
    graph = FakeGraph(
        {"g1": "global", "g2": "global", "r1": "regional", "r2": "regional", "r3": "regional"},
        {"r1": {"g1", "r2"}, "r2": {"g1", "g2"}, "r3": {"r1", "r2"}},
    )

    assert [(n, m.split(": ")[0]) for n, m in find_cardinality_violations(graph)] == [
        ("r2", "A regional genre has 2 global parents")
    ]


def test_node_without_state_then_ignored():
    graph = FakeGraph({"x": None, "a": "global", "b": "global"}, {"x": {"a", "b"}})

    assert find_cardinality_violations(graph) == []
