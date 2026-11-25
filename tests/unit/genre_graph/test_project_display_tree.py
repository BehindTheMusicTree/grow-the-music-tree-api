import pytest
from the_music_tree_genre_graph.validation import GraphValidationError

from grow.genre_graph.service import _project_display_tree


class FakeGraph:
    def __init__(self, display_parents):
        self._parents = display_parents

    def node(self, identity):
        parent = self._parents[identity]
        return {"displayParentId": parent} if parent else {}


def test_chain_then_parent_and_root_projected():
    graph = FakeGraph({"a": None, "b": "a", "c": "b"})
    bindings = {"a": 1, "b": 2, "c": 3}

    assert _project_display_tree(graph, bindings) == {1: (None, 1), 2: (1, 1), 3: (2, 1)}


def test_cycle_then_validation_error():
    graph = FakeGraph({"a": "b", "b": "a"})

    with pytest.raises(GraphValidationError, match="cycle"):
        _project_display_tree(graph, {"a": 1, "b": 2})
