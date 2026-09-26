from typing import TYPE_CHECKING, Any

from django.db import transaction
from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_genre_kit.criteria.children.genre.AbstractGenreManager import AbstractGenreManager

from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry

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

    def _lock(self, instance: Genre) -> None:
        instance.is_manually_edited = True
        instance.save(update_fields=["is_manually_edited"])

    def _on_created(self, instance: Genre, *, actor: Any = None) -> None:
        super()._on_created(instance, actor=actor)
        if actor is not None:
            self._lock(instance)
        HistoryEntry.objects.record(instance, action=HistoryAction.CREATED, actor=actor)

    def _on_bulk_created(self, instances: list[Genre], *, actor: Any = None) -> None:
        super()._on_bulk_created(instances, actor=actor)
        for instance in instances:
            HistoryEntry.objects.record(instance, action=HistoryAction.CREATED, actor=actor)

    def _on_parent_changed(
        self, instance: Genre, *, old_parent: Genre | None, old_root: Genre, root_changed: bool, actor: Any = None
    ) -> None:
        super()._on_parent_changed(
            instance, old_parent=old_parent, old_root=old_root, root_changed=root_changed, actor=actor
        )
        if actor is not None:
            self._lock(instance)
        HistoryEntry.objects.record(
            instance,
            action=HistoryAction.PARENT_CHANGED,
            actor=actor,
            old_value=old_parent.name if old_parent else None,
            new_value=instance.parent.name if instance.parent else None,
        )

    def _on_renamed(self, instance: Genre, *, old_name: str, actor: Any = None) -> None:
        if actor is not None:
            instance.has_name_conflict = False
            instance.save(update_fields=["has_name_conflict"])
            self._lock(instance)
        HistoryEntry.objects.record(
            instance, action=HistoryAction.RENAMED, actor=actor, old_value=old_name, new_value=instance.name
        )

    def assert_required_roots_present(self, user: Any) -> None:
        existing_root_names = set(self.get_roots(user).filter(is_excluded=False).values_list("_name", flat=True))
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
        HistoryEntry.objects.record(instance, action=HistoryAction.DELETED, actor=actor, old_value=instance.name)
        super().delete_instance(instance, actor=actor)
        if was_required_root:
            self.assert_required_roots_present(user)

    @transaction.atomic
    def exclude_instance(self, instance: Genre, actor: Any = None) -> Genre:
        """Soft-remove a wikidata-backed genre: excluded from the visible tree, protected from
        re-creation/deletion by the next pipeline import, unlike a real DELETE (see
        `AbstractGenreCriteria.is_excluded`)."""
        was_required_root = self._is_required_root(instance)
        instance.is_excluded = True
        instance.save(update_fields=["is_excluded"])
        if was_required_root:
            self.assert_required_roots_present(instance.user)
        HistoryEntry.objects.record(instance, action=HistoryAction.EXCLUDED, actor=actor)
        return instance

    def get_name_conflict_groups(self, user: Any) -> list[dict[str, Any]]:
        """Groups each import-flagged genre (named `"<base> (<wikidata_id>)"`, see the genre kit's
        `_disambiguate_conflicting_names`) with every genre whose name is its base name."""
        flagged = list(self.filter(user=user, has_name_conflict=True))
        base_names = {genre.pk: genre.name.removesuffix(f" ({genre.wikidata_id})") for genre in flagged}
        groups: dict[str, dict[str, Any]] = {}
        for genre in flagged:
            base_name = base_names[genre.pk]
            groups.setdefault(base_name.lower(), {"name": base_name, "genres": []})["genres"].append(genre)
        for group in groups.values():
            group["genres"] = [
                *self.filter(user=user, _name__iexact=group["name"]).exclude(pk__in=base_names),
                *group["genres"],
            ]
        return sorted(groups.values(), key=lambda group: group["name"].lower())

    @transaction.atomic
    def validate_name_conflict_group(self, user: Any, names: dict[Any, str], actor: Any = None) -> None:
        """Applies the admin's final `names` (uuid -> name) to a conflict group and marks each of its
        flagged genres as reviewed: renamed ones via `_on_renamed`, unchanged ones here."""
        genres = {genre.uuid: genre for genre in self.filter(user=user, uuid__in=names)}
        missing = [str(uuid) for uuid in names if uuid not in genres]
        if missing:
            raise AppValidationException(
                field_name=missing[0],
                message="Genre not found",
                field_validation_error_code=FieldValidationErrorCode.REFERENCE_INVALID,
            )
        # The unique-name constraint spans the whole criteria table, case-insensitively.
        base_model = (self.model._meta.get_parent_list() or [self.model])[-1]
        taken = {
            name.lower()
            for name in base_model._base_manager.filter(user=user)
            .exclude(pk__in=[genre.pk for genre in genres.values()])
            .values_list("_name", flat=True)
        }
        for uuid, name in names.items():
            if name.lower() in taken:
                raise AppValidationException(
                    field_name=str(uuid),
                    message=f'The name "{name}" is already used',
                    field_validation_error_code=FieldValidationErrorCode.NAME_DUPLICATE,
                )
            taken.add(name.lower())
        # Park renamed rows on their uuid first, so names can be swapped within the group without
        # tripping the unique-name constraint mid-loop.
        for uuid, name in names.items():
            if name != genres[uuid].name:
                self.filter(pk=genres[uuid].pk).update(_name=str(uuid))
        for uuid, name in names.items():
            genre = genres[uuid]
            if name != genre.name:
                self.update_instance(genre, actor=actor, name=name)
            elif genre.has_name_conflict:
                genre.has_name_conflict = False
                genre.save(update_fields=["has_name_conflict"])
                self._lock(genre)
                HistoryEntry.objects.record(genre, action=HistoryAction.NAME_CONFLICT_RESOLVED, actor=actor)

    @transaction.atomic
    def update_instance(self, instance: Genre, actor: Any = None, **kwargs) -> Genre:
        was_required_root = self._is_required_root(instance)
        updated = super().update_instance(instance, actor=actor, **kwargs)
        if was_required_root:
            self.assert_required_roots_present(updated.user)
        return updated
