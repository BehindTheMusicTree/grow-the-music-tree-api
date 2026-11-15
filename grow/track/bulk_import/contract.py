from rest_framework.exceptions import ValidationError
from the_music_tree_genre_kit.genre_graph.models import GenreGraphDataset

from grow.genre_graph.service import DATASET_KEY


def require_legacy_import_contract() -> None:
    if GenreGraphDataset.objects.filter(pk=DATASET_KEY).exists():
        raise ValidationError(
            "Legacy song imports cannot publish into an active reference graph; "
            "semantic assignment imports are required."
        )
