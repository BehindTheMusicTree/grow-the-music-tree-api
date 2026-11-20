from dataclasses import dataclass

from grow.genre_graph.closure import GraphClosure


@dataclass
class GenreScopedCounts:
    genre_only_tracks_count: int
    genre_and_subgenres_tracks_count: dict[str, int]

    @property
    def default_count(self):
        values = self.genre_and_subgenres_tracks_count
        return values.get("canonical", values["all"])


def catalogue_counts(exact: dict, closure: GraphClosure, *, genres=None) -> dict:
    """Project exact catalogue buckets onto each genre's kit closure.

    Each song sits in exactly one bucket, so summing the buckets of a closure's deduplicated descendant set
    counts every song once, however many paths reach it.
    """
    result = {}
    for genre in closure.selections if genres is None else genres:
        scopes = closure.selections[genre]
        values = {scope.value: sum(exact[node] for node in exact.keys() & nodes) for scope, nodes in scopes.items()}
        result[genre] = GenreScopedCounts(exact.get(genre, 0), values)
    genreless = exact.get(None, 0)
    result[None] = GenreScopedCounts(genreless, {"all": genreless})
    return result
