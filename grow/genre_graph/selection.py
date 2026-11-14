from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError
from the_music_tree_genre_kit.criteria.selection.coverage import CriteriaCoverage
from the_music_tree_genre_kit.genre_graph.graph import GraphValidationError
from the_music_tree_genre_kit.genre_graph.storage import effective_attributions, select_tracks

from grow.genre_graph.service import DATASET_KEY, reference_dataset
from grow.genre_music.selection import parse_subgenres
from grow.model.criteria.children.genre.Genre import Genre


def require_reference_graph() -> None:
    try:
        reference_dataset()
    except GraphValidationError as error:
        raise ValidationError({"graph": str(error)}) from error


def attributed_songs(songs: QuerySet) -> QuerySet:
    require_reference_graph()
    return songs.filter(pk__in=effective_attributions(key=DATASET_KEY).values("track_id"))


def select_songs(songs: QuerySet, *, genre_id, coverage: CriteriaCoverage, subgenres=None) -> QuerySet:
    require_reference_graph()
    try:
        genre = Genre.objects.select_related("graph_node").get(pk=genre_id, user__isnull=True)
    except Genre.DoesNotExist:
        return songs.none()
    node = genre.graph_node
    if node is None or node.dataset_id != DATASET_KEY:
        raise ValidationError({"genre": "Genre has no reference graph identity mapping."})
    tree = "canonical" if node.canonical_state == "canonical" else "regional"
    scope = parse_subgenres(subgenres, coverage, tree)
    return select_tracks(
        songs,
        key=DATASET_KEY,
        identity=node.identity,
        scope=scope.value if scope is not None else "all",
        include_descendants=coverage != CriteriaCoverage.ONLY,
    )
