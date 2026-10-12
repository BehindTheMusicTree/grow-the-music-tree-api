from typing import TYPE_CHECKING, Any, TypeVar

from the_music_tree_genre_kit.criteria.AbstractCriteriaManager import AbstractCriteriaManager

if TYPE_CHECKING:
    from django.db import models

    from .Criteria import Criteria

T = TypeVar("T", bound="Criteria")


class CriteriaManager(AbstractCriteriaManager[T]):
    model: type[T]

    @property
    def lineage_rel_model(self) -> type[models.Model]:
        from .lineage_rel.CriteriaLineageRel import CriteriaLineageRel

        return CriteriaLineageRel

    def _on_created(self, instance: T, *, actor: Any = None) -> None:
        from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

        CriteriaPlaylist.objects.create(user=instance.user, criteria=instance, type=instance.type)

    def _on_bulk_created(self, instances: list[T], *, actor: Any = None) -> None:
        from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

        CriteriaPlaylist.objects.bulk_create_for_criteria(instances)
