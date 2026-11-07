import pytest

from grow.genre_music.selection import (
    SubgenreScope,
    all_genre_selections,
    genre_graph,
    genre_tree_snapshot,
    selected_genres,
)
from tests.utils.ModelFixtureFactory import ModelFixtureFactory


@pytest.fixture
def graph():
    trees = {
        "root": "canonical",
        "canonical": "canonical",
        "regional": "regional",
        "diamond": "regional",
        "behind_regional": "canonical",
    }
    edges = [
        ("root", "canonical"),
        ("root", "regional"),
        ("canonical", "diamond"),
        ("regional", "diamond"),
        ("regional", "behind_regional"),
    ]
    return trees, edges


def test_canonical_scopes_follow_primary_paths_and_deduplicate(graph):
    trees, edges = graph
    assert selected_genres("root", trees, edges, SubgenreScope.CANONICAL) == {"root", "canonical"}
    assert selected_genres("root", trees, edges, SubgenreScope.REGIONAL) == {"root", "regional", "diamond"}
    assert selected_genres("root", trees, edges, SubgenreScope.ALL) == {"root", "canonical", "regional", "diamond"}


def test_regional_selection_includes_all_descendants(graph):
    trees, edges = graph
    assert selected_genres("regional", trees, edges, SubgenreScope.ALL) == {"regional", "diamond", "behind_regional"}
    with pytest.raises(ValueError, match="Regional genres require the all scope"):
        selected_genres("regional", trees, edges, SubgenreScope.CANONICAL)


def test_selection_rejects_incomplete_graph(graph):
    trees, edges = graph
    with pytest.raises(ValueError, match="Primary edge references a missing genre"):
        selected_genres("root", trees, [*edges, ("root", "missing")], SubgenreScope.ALL)


def test_bottom_up_projection_matches_each_selection(graph):
    trees, edges = graph
    for genre, scopes in all_genre_selections(trees, edges).items():
        for scope, selection in scopes.items():
            assert selection == selected_genres(genre, trees, edges, scope)


def test_bottom_up_projection_rejects_cycles(graph):
    trees, edges = graph
    with pytest.raises(ValueError, match="contains a cycle"):
        all_genre_selections(trees, [*edges, ("diamond", "root")])


@pytest.mark.django_db
def test_genre_graph_reads_primary_edges_in_one_query_then_only_the_version(django_assert_num_queries):
    factory = ModelFixtureFactory(default_user=None)
    root = factory.create_genre("Graph root")
    parent = factory.create_genre("Graph parent", parent=root)
    child = factory.create_genre("Graph child", parent=parent)
    child.additional_primary_parents.add(root)

    with django_assert_num_queries(2):
        trees, edges = genre_graph()
    with django_assert_num_queries(1):
        assert genre_graph() == (trees, edges)

    assert {root.pk, parent.pk, child.pk} <= trees.keys()
    assert {(root.pk, parent.pk), (parent.pk, child.pk), (root.pk, child.pk)} <= set(edges)
    assert genre_tree_snapshot().playlists[child.pk] == child.criteria_playlist.uuid


@pytest.mark.django_db
def test_genre_graph_reloads_after_a_tree_write():
    factory = ModelFixtureFactory(default_user=None)
    root = factory.create_genre("Graph root")
    before, _ = genre_graph()
    child = factory.create_genre("Graph child", parent=root)

    trees, edges = genre_graph()

    assert child.pk not in before
    assert child.pk in trees
    assert (root.pk, child.pk) in edges
