from dataclasses import dataclass

from grow.genre_music.selection import all_genre_selections, genre_graph


@dataclass
class GenreScopedCounts:
    genre_only_tracks_count: int
    genre_and_subgenres_tracks_count: dict[str, int]

    @property
    def default_count(self):
        values = self.genre_and_subgenres_tracks_count
        return values.get("canonical", values["all"])


def catalogue_counts(exact: dict, graph=None, *, selections=None) -> dict:
    """Project exact catalogue counts onto each distinct primary-path selection."""
    trees, edges = graph if graph is not None else genre_graph()
    result = {}
    closures = selections if selections is not None else all_genre_selections(trees, edges)
    for genre, scopes in closures.items():
        values = {scope.value: sum(exact[node] for node in exact.keys() & nodes) for scope, nodes in scopes.items()}
        result[genre] = GenreScopedCounts(exact.get(genre, 0), values)
    genreless = exact.get(None, 0)
    result[None] = GenreScopedCounts(genreless, {"all": genreless})
    return result
