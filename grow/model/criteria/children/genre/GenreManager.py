from typing import TYPE_CHECKING, Any

from django.db import transaction
from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_genre_kit.criteria.children.genre.AbstractGenreManager import AbstractGenreManager
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName

from grow.curation.lists import CURATION_LISTS, EXCLUDED_GENRE_LISTS
from grow.curation.rows import InvalidRow, find_parent_rule, lock_writes
from grow.model.curation.CurationEntry import CurationEntry
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

    @staticmethod
    def _is_wikidata_item(instance: Genre) -> bool:
        """App-created genres (no wikidata_id) and the pipeline's synthetic `LOCAL:` items aren't in the Wikidata
        tree the curation lists apply to, so the lock alone keeps their edits."""
        return instance.wikidata_id is not None and instance.wikidata_id.startswith("Q")

    @staticmethod
    def _lock_curation_writes(actor: Any) -> None:
        """Admin edits upsert curation rules after locking genre rows; taking the curation write lock first keeps
        that order the same in every transaction, so two concurrent edits can't deadlock on it."""
        if actor is not None:
            lock_writes(CurationEntry.objects.all())

    @staticmethod
    def _invalid(field_name: str, message: str) -> AppValidationException:
        return AppValidationException(
            field_name=field_name,
            message=message,
            field_validation_error_code=FieldValidationErrorCode.REFERENCE_INVALID,
        )

    def _upsert_rule(self, instance: Genre, list_name: str, actor: Any, **row: str) -> None:
        """Mirrors an admin edit of a wikidata item into the curation list the pipeline reads, so the next import
        reproduces it instead of only skipping the locked row."""
        if not self._is_wikidata_item(instance):
            return
        columns = CURATION_LISTS[list_name].columns
        row = {"item_id": instance.wikidata_id, **row}
        if "item_label" in columns:
            row["item_label"] = instance.name
        if "reason" in columns:
            row["reason"] = f"grow admin edit by {actor.profile.pseudo}"
        try:
            CurationEntry.objects.upsert(list_name, row, actor=actor)
        except InvalidRow as e:
            field_name, message = next(iter(e.errors.items()))
            raise self._invalid(field_name, f"Can't record this edit in {list_name}: {message}") from e

    def _reparent_rule(self, instance: Genre) -> dict[str, str]:
        """The `main_parent` row for an admin reparent, or a 400 when no curation list can express it."""
        parent_item_id, parent_excluded = self.filter(pk=instance.parent_id).values_list(
            "wikidata_id", "is_excluded"
        ).first() or (None, False)
        if instance.tree_name != CriteriaTreeName.CANONICAL:
            # The new parent may be a regional overview (`regional_overrides`) or a genre (`main_parent`),
            # which grow can't tell apart, and `regional_secondary_parents` adds an edge rather than moving one.
            message = "Regional genres can't be reparented here; edit the regional curation lists instead"
        elif instance.parent_id is None:
            message = "A wikidata-backed genre can't be made a root; no curation list expresses it"
        elif parent_item_id is None:
            message = "A wikidata-backed genre's new parent must be wikidata-backed too"
        elif instance.is_excluded or parent_excluded:
            message = "An excluded genre can't be reparented or be a new parent; the pipeline prunes it"
        else:
            return {"parent_item_id": parent_item_id, "exclude_other_parents": "true"}
        raise self._invalid("parent", message)

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
            if self._is_wikidata_item(instance):
                self._upsert_rule(instance, "main_parent", actor, **self._reparent_rule(instance))
            if instance.parent_id is not None:
                instance.is_unaccepted_root = False
                instance.save(update_fields=["is_unaccepted_root"])
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
            self._upsert_rule(instance, "label_overrides", actor, display_label=instance.name)
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
    def exclude_instance(self, instance: Genre, category: str, actor: Any = None) -> Genre:
        """Soft-remove a wikidata-backed genre: excluded from the visible tree, protected from
        re-creation/deletion by the next pipeline import, unlike a real DELETE (see
        `AbstractGenreCriteria.is_excluded`)."""
        self._lock_curation_writes(actor)
        was_required_root = self._is_required_root(instance)
        instance.is_excluded = True
        instance.save(update_fields=["is_excluded"])
        if actor is not None and self._is_wikidata_item(instance):
            rule = find_parent_rule(CurationEntry.objects.filter(user=None), instance.wikidata_id)
            if rule is not None:
                raise self._invalid(
                    "category", f"Remove the {rule.list_name} rule for {rule.key} first; it references this genre"
                )
            self._upsert_rule(instance, EXCLUDED_GENRE_LISTS[category], actor)
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
        self._lock_curation_writes(actor)
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

    def get_unaccepted_roots(self, user: Any) -> list[Genre]:
        return list(self.filter(user=user, is_unaccepted_root=True, is_excluded=False).order_by("_name"))

    @transaction.atomic
    def accept_roots(self, user: Any, uuids: list[Any], actor: Any = None) -> None:
        self._lock_curation_writes(actor)
        genres = {genre.uuid: genre for genre in self.filter(user=user, uuid__in=uuids, is_unaccepted_root=True)}
        missing = [str(uuid) for uuid in uuids if uuid not in genres]
        if missing:
            raise AppValidationException(
                field_name=missing[0],
                message="Unaccepted root genre not found",
                field_validation_error_code=FieldValidationErrorCode.REFERENCE_INVALID,
            )
        for genre in genres.values():
            genre.is_unaccepted_root = False
            genre.save(update_fields=["is_unaccepted_root"])
            self._lock(genre)
            if actor is not None:
                self._upsert_rule(genre, "accepted_canonical_roots", actor)
            HistoryEntry.objects.record(genre, action=HistoryAction.ROOT_ACCEPTED, actor=actor)

    @transaction.atomic
    def update_instance(self, instance: Genre, actor: Any = None, **kwargs) -> Genre:
        self._lock_curation_writes(actor)
        was_required_root = self._is_required_root(instance)
        updated = super().update_instance(instance, actor=actor, **kwargs)
        if was_required_root:
            self.assert_required_roots_present(updated.user)
        return updated
