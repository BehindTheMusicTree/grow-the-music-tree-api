from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError
from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.criteria.selection.coverage import CriteriaCoverage
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAccess
from the_music_tree_genre_kit.genre_graph.storage import effective_attributions, select_tracks

from grow.genre_graph.closure import parse_subgenres
from grow.genre_graph.service import DATASET_KEY, reference_dataset
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
    if not node.is_active:
        return songs.none()
    scope = parse_subgenres(subgenres, coverage, node.canonical_state)
    return select_tracks(
        songs,
        node=node,
        scope=scope.value if scope is not None else "all",
        include_descendants=coverage != CriteriaCoverage.ONLY,
    )


def selected_genre_ids(node, scope, *, include_descendants: bool = True) -> QuerySet:
    """Genre uuids selected by a node: the kit's access rows projected onto genres, as an uncorrelated subquery.

    Usable in any filter on a column carrying a genre id (``TrackPlaylistRel.genre_id``,
    ``GenreMembershipCount.genre_id``, ``Song.membership_genre_id``); issues no query until evaluated.
    """
    if not node.is_active:
        return Genre.objects.none().values("pk")
    if include_descendants:
        nodes = GenreGraphAccess.objects.filter(
            dataset_id=node.dataset_id, ancestor_id=node.pk, scope=scope.value
        ).values("descendant_id")
        return Genre.objects.filter(user__isnull=True, graph_node_id__in=nodes).values("pk")
    return Genre.objects.filter(user__isnull=True, graph_node_id=node.pk).values("pk")
