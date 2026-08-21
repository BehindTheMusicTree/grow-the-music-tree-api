from typing import TYPE_CHECKING, TypeVar

from the_music_tree_genre_kit.criteria.AbstractCriteriaManager import AbstractCriteriaManager

from .Fields import Fields

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

    def _on_created(self, instance: T) -> None:
        from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

        CriteriaPlaylist.objects.create(user=instance.user, criteria=instance, type=instance.type)

    def _on_parent_changed(
        self, instance: T, *, old_parent: Criteria | None, old_root: Criteria, root_changed: bool
    ) -> None:
        from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist

        playlist_parent = instance.parent.criteria_playlist if instance.parent else None
        CriteriaPlaylist.objects.update_instance(
            instance=instance.criteria_playlist, **{Fields.PARENT: playlist_parent}
        )

        common_criteria = self.get_common_ascendant(instance, old_parent)
        CriteriaPlaylist.objects.update_ascendants_tracks(
            instance=instance.criteria_playlist, old_parent=old_parent, common_criteria=common_criteria
        )

        if root_changed:
            CriteriaPlaylist.objects.update_instance_and_children_root(
                instance=instance.criteria_playlist, root=instance.root.criteria_playlist
            )
