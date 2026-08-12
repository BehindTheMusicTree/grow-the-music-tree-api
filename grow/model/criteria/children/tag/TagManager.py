from typing import TYPE_CHECKING

from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks

from ...CriteriaManager import CriteriaManager

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from .Tag import Tag


class TagManager(CriteriaManager):
    model: "Tag"

    def _get_criteria_type(self) -> CriteriaType:
        return CriteriaType(pk=CriteriaTypePks.TAG)

    def get_queryset(self) -> "QuerySet[Tag]":
        return super().get_queryset().filter(type_id=CriteriaTypePks.TAG)
