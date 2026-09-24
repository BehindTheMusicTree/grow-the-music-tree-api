from typing import TYPE_CHECKING, Any

from django.db import transaction
from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_genre_kit.criteria.children.genre.AbstractGenreManager import AbstractGenreManager

from ...CriteriaManager import CriteriaManager

if TYPE_CHECKING:
    from .Genre import Genre

# Extension point: add future required root labels here (see ARCHITECTURE.md).
REQUIRED_ROOT_GENRE_NAMES: frozenset[str] = frozenset({"Mainstream Pop"})


class GenreManager(AbstractGenreManager, CriteriaManager):
    model: Genre

    def _get_direct_tracks(self, instance: Genre) -> list:
        return list(instance.tracks.all())

    def _is_required_root(self, instance: Genre) -> bool:
        return instance.parent_id is None and instance.name in REQUIRED_ROOT_GENRE_NAMES

    def assert_required_roots_present(self, user: Any) -> None:
        existing_root_names = set(self.get_roots(user).values_list("_name", flat=True))
        missing_root_names = sorted(REQUIRED_ROOT_GENRE_NAMES - existing_root_names)
        if missing_root_names:
            names = ", ".join(f'"{name}"' for name in missing_root_names)
            raise AppValidationException(
                field_name="name",
                message=f"A root genre named {names} is required.",
                field_validation_error_code=FieldValidationErrorCode.DEPENDENCY_MISSING,
            )

    @transaction.atomic
    def create(self, actor: Any = None, **kwargs) -> Genre:
        # essential_tracks is a many-to-many field: it can't be passed to Model(**kwargs)
        # before the instance has a primary key, so it's set separately after creation.
        essential_tracks = kwargs.pop("essential_tracks", None)
        instance = super().create(actor=actor, **kwargs)
        if essential_tracks is not None:
            instance.essential_tracks.set(essential_tracks)
        return instance

    @transaction.atomic
    def delete_instance(self, instance: Genre, actor: Any = None) -> None:
        was_required_root = self._is_required_root(instance)
        user = instance.user
        super().delete_instance(instance, actor=actor)
        if was_required_root:
            self.assert_required_roots_present(user)

    @transaction.atomic
    def update_instance(self, instance: Genre, actor: Any = None, **kwargs) -> Genre:
        was_required_root = self._is_required_root(instance)
        updated = super().update_instance(instance, actor=actor, **kwargs)
        if was_required_root:
            self.assert_required_roots_present(updated.user)
        return updated
