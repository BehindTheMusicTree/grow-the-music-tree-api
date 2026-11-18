from functools import wraps

from the_music_tree_genre_kit.genre_graph.storage import graph_read_snapshot


def graph_snapshot(view):
    """Keep all database reads for a response in the same graph snapshot."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        with graph_read_snapshot():
            return view(*args, **kwargs)

    return wrapped
