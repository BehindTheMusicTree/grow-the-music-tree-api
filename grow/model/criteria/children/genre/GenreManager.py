import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.search import TrigramWordSimilarity
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Count, F, QuerySet
from django.db.models.functions import Coalesce
from the_music_tree_api_kit.exception.validation.app.AppValidationException import AppValidationException
from the_music_tree_api_kit.exception.validation.FieldValidationErrorCode import FieldValidationErrorCode
from the_music_tree_genre_kit.criteria.children.genre.AbstractGenreManager import AbstractGenreManager
from the_music_tree_genre_kit.criteria.CriteriaSide import CriteriaSide
from the_music_tree_genre_kit.criteria.CriteriaTreeName import CriteriaTreeName
from the_music_tree_genre_kit.criteria.Fields import Fields

from grow.curation.admin_rules import invalid, upsert_admin_rule
from grow.curation.edges import find_edge_parent_rule
from grow.curation.lists import ADDITION_LISTS, EXCLUDED_GENRE_LISTS
from grow.curation.rows import KEY_SEPARATOR, POP_SIDE_LIST, InvalidRow, lock_writes
from grow.genre_music.source_gate import lock_catalogue_sources
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from grow.search.trigram import fold_query, match_rank
from grow.track.direct_songs_count import adjust_direct_songs_count

from ...CriteriaManager import CriteriaManager

if TYPE_CHECKING:
    from .Genre import Genre

# Extension point: add future required root labels here (see ARCHITECTURE.md).
REQUIRED_ROOT_GENRE_NAMES: frozenset[str] = frozenset({"Mainstream Pop"})

# Songs a batch delete left genreless, handed from `_on_tracks_genre_moved` to `_on_before_delete_many`.
_genreless_song_pks: ContextVar[list | None] = ContextVar("genreless_song_pks", default=None)


class GenreManager(AbstractGenreManager, CriteriaManager):
    model: Genre

    def _get_direct_tracks(self, instance: Genre) -> QuerySet:
        return instance.tracks.all()

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
    def _is_pipeline_item(instance: Genre) -> bool:
        """Wikidata items and the curated `LOCAL:` nodes: the ids the pipeline's edge rules can name."""
        return instance.wikidata_id is not None

    @staticmethod
    def _is_local_item(instance: Genre) -> bool:
        return instance.wikidata_id is not None and instance.wikidata_id.startswith("LOCAL:")

    def _mint_local_id(self, name: str) -> str:
        slug = re.sub(
            r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        )
        slug = slug.strip("-") or "genre"
        taken = set(CurationEntry.objects.filter(user=None, list_name__in=ADDITION_LISTS).values_list("key", flat=True))
        candidate, n = f"LOCAL:{slug}", 1
        while candidate in taken or self.filter(wikidata_id=candidate).exists():
            n += 1
            candidate = f"LOCAL:{slug}-{n}"
        return candidate

    def _ensure_pipeline_item(self, genre: Genre, actor: Any) -> str:
        """The genre's pipeline item id. An app-created genre is adopted as a curated `LOCAL:` grouping node (and,
        recursively, so are its app-created ancestors), so the edge rules can name it and the next run rebuilds it."""
        if self._is_pipeline_item(genre):
            return genre.wikidata_id
        if genre.tree_name != CriteriaTreeName.CANONICAL or genre.is_excluded:
            raise self._invalid("parent", "A regional or excluded genre can't become a new parent")
        # `parent` is the base `Criteria` row: the adoption reads the `Genre` fields.
        parent_item_id = (
            self._ensure_pipeline_item(self.get(pk=genre.parent_id), actor) if genre.parent_id is not None else None
        )
        item_id = self._mint_local_id(genre.name)
        upsert_admin_rule(
            "canonical_parent_additions",
            {
                "item_id": item_id,
                "label": genre.name,
                "reason": f"grow admin: app-created genre adopted as a parent by {actor.profile.pseudo}",
            },
            actor,
        )
        genre.wikidata_id = item_id
        genre.save(update_fields=["wikidata_id"])
        self._lock(genre)
        self._upsert_edge(
            genre, GenreEdgeRule.Relation.CANONICAL_PARENT, parent_item_id, actor, exclude_other_parents=True
        )
        HistoryEntry.objects.record(
            genre, action=HistoryAction.UPDATED, actor=actor, new_value=f"adopted into curation as {item_id}"
        )
        return item_id

    @staticmethod
    def _lock_curation_writes(actor: Any) -> None:
        """Admin edits upsert curation rules after locking genre rows; taking the curation write lock first keeps
        that order the same in every transaction, so two concurrent edits can't deadlock on it."""
        if actor is not None:
            lock_writes(CurationEntry.objects.all())

    @staticmethod
    def _invalid(field_name: str, message: str) -> AppValidationException:
        return invalid(field_name, message)

    def _upsert_rule(self, instance: Genre, list_name: str, actor: Any, **row: str) -> None:
        """Mirrors an admin edit of a wikidata item into the curation list the pipeline reads, so the next import
        reproduces it instead of only skipping the locked row."""
        if not self._is_wikidata_item(instance):
            return
        row = {"item_id": instance.wikidata_id, **row}
        upsert_admin_rule(list_name, row, actor)

    def _upsert_edge(
        self,
        instance: Genre,
        relation: str,
        parent_item_id: str | None,
        actor: Any,
        *,
        action: str | None = None,
        exclude_other_parents: bool | None = None,
    ) -> None:
        """Mirrors an admin edit of a pipeline item's parent into the edge rules the pipeline reads."""
        if not self._is_pipeline_item(instance):
            return
        try:
            GenreEdgeRule.objects.upsert(
                relation,
                instance.wikidata_id,
                parent_item_id,
                action=action,
                exclude_other_parents=exclude_other_parents,
                reason=f"grow admin edit by {actor.profile.pseudo}",
                actor=actor,
            )
        except InvalidRow as e:
            message = next(iter(e.errors.values()))
            raise invalid("parent", f"Can't record this edit as a {relation} edge: {message}") from e
        except ValidationError as e:
            raise invalid("parent", f"Can't record this edit as a {relation} edge: {'; '.join(e.messages)}") from e

    def _reparent_target(self, instance: Genre, actor: Any) -> str | None:
        """The parent item id of an admin reparent (None for a root), or a 400 when no edge can express it."""
        parent_excluded = self.filter(pk=instance.parent_id).values_list("is_excluded", flat=True).first() or False
        if instance.tree_name != CriteriaTreeName.CANONICAL:
            # The new parent may be a regional overview (`regional_overviews`) or a regional genre
            # (`regional_genre_parent`), which grow can't tell apart.
            message = "Regional genres can't be reparented here; edit the regional curation lists instead"
        elif instance.is_excluded or parent_excluded:
            message = "An excluded genre can't be reparented or be a new parent; the pipeline prunes it"
        elif instance.parent_id is None:
            return None
        else:
            return self._ensure_pipeline_item(self.get(pk=instance.parent_id), actor)
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
            if self._is_pipeline_item(instance):
                # One canonical assertion per item: the edge replaces a root or an earlier parent, and an edge of
                # the same pair in another relation (such as a secondary `add`).
                self._upsert_edge(
                    instance,
                    GenreEdgeRule.Relation.CANONICAL_PARENT,
                    self._reparent_target(instance, actor),
                    actor,
                    exclude_other_parents=True,
                )
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

    @staticmethod
    def _links_without_new_parent(instance: Genre, new_parent: Genre, kwargs: dict[str, Any]) -> bool:
        """A parent can only be linked once: when `new_parent` is already a secondary or additional primary parent,
        puts that field minus it in `kwargs`. Returns whether it was a secondary parent."""
        was_secondary = False
        for field in ("secondary_parents", "additional_primary_parents"):
            if field in kwargs or (
                field == "additional_primary_parents" and not instance.allows_multiple_primary_parents
            ):
                continue
            links = list(getattr(instance, field).all())
            if any(p.pk == new_parent.pk for p in links):
                kwargs[field] = [p for p in links if p.pk != new_parent.pk]
                was_secondary = was_secondary or field == "secondary_parents"
        return was_secondary

    def _drop_secondary_add_rule(self, instance: Genre, anchor_parent_pk: Any, actor: Any) -> None:
        """The `add` rule of an edge that became the main parent would make gold raise on the duplicate. A `remove`
        rule is kept by an actor-less move, it applies again if the main parent later moves away."""
        anchor_parent_item_id = self.filter(pk=anchor_parent_pk).values_list("wikidata_id", flat=True).first()
        if instance.wikidata_id is None or anchor_parent_item_id is None:
            return
        rules = GenreEdgeRule.objects.filter(
            user=None,
            relation=GenreEdgeRule.Relation.SECONDARY_PARENT,
            item_id=instance.wikidata_id,
            parent_item_id=anchor_parent_item_id,
            action=GenreEdgeRule.Action.ADD,
        )
        for rule in rules:
            GenreEdgeRule.objects.delete_instance(rule, actor=actor)

    def _on_renamed(self, instance: Genre, *, old_name: str, actor: Any = None) -> None:
        if actor is not None:
            instance.has_name_conflict = False
            instance.save(update_fields=["has_name_conflict"])
            self._lock(instance)
            self._upsert_rule(instance, "label_overrides", actor, display_label=instance.name)
            if self._is_local_item(instance):
                self._relabel_addition(instance, actor)
        HistoryEntry.objects.record(
            instance, action=HistoryAction.RENAMED, actor=actor, old_value=old_name, new_value=instance.name
        )

    @staticmethod
    def _relabel_addition(instance: Genre, actor: Any) -> None:
        entry = CurationEntry.objects.filter(
            user=None, list_name="canonical_parent_additions", key=instance.wikidata_id
        ).first()
        if entry is not None:
            upsert_admin_rule("canonical_parent_additions", {**entry.row, "label": instance.name}, actor)

    def _release_local_items(self, instances: list[Genre], actor: Any) -> None:
        """Deleting a curated `LOCAL:` node splices it out of the edge rules like the kit does for the rows: its
        children's edges move to its parent item (or the accepted root), and its own edges and addition go."""
        if actor is None:
            return
        gone = {i.wikidata_id for i in instances if self._is_local_item(i)}
        # Snapshot before any deletion: a chain of deleted nodes splices to the nearest surviving ancestor.
        parent_of = dict(
            GenreEdgeRule.objects.filter(
                user=None, relation=GenreEdgeRule.Relation.CANONICAL_PARENT, item_id__in=gone
            ).values_list("item_id", "parent_item_id")
        )

        def survivor(item_id: str) -> str | None:
            parent = parent_of.get(item_id)
            while parent in gone:
                parent = parent_of.get(parent)
            return parent

        for item_id in sorted(gone):
            new_parent = survivor(item_id)
            for rule in list(GenreEdgeRule.objects.filter(user=None, parent_item_id=item_id)):
                if rule.relation == GenreEdgeRule.Relation.CANONICAL_PARENT:
                    GenreEdgeRule.objects.delete_instance(rule, actor=actor)
                    if rule.item_id not in gone:
                        self._upsert_edge_by_id(rule.item_id, new_parent, actor)
                else:
                    GenreEdgeRule.objects.delete_instance(rule, actor=actor)
            for rule in list(GenreEdgeRule.objects.filter(user=None, item_id=item_id)):
                GenreEdgeRule.objects.delete_instance(rule, actor=actor)
            for entry in list(CurationEntry.objects.filter(user=None, key=item_id, list_name__in=ADDITION_LISTS)):
                CurationEntry.objects.delete_instance(entry, actor=actor)

    @staticmethod
    def _upsert_edge_by_id(item_id: str, parent_item_id: str | None, actor: Any) -> None:
        try:
            GenreEdgeRule.objects.upsert(
                GenreEdgeRule.Relation.CANONICAL_PARENT,
                item_id,
                parent_item_id,
                exclude_other_parents=True,
                reason=f"grow admin edit by {actor.profile.pseudo}",
                actor=actor,
            )
        except (InvalidRow, ValidationError) as e:
            raise invalid("parent", f"Can't repoint the edge of {item_id}: {e}") from e

    def _on_side_changed(self, instance: Genre, *, old_side: str, actor: Any = None) -> None:
        if actor is not None:
            self._lock(instance)
            self._write_pop_side_rule(instance, actor)
        HistoryEntry.objects.record(
            instance,
            action=HistoryAction.SIDE_CHANGED,
            actor=actor,
            old_value=old_side,
            new_value=instance.side or CriteriaSide.CORE,
        )

    def _write_pop_side_rule(self, instance: Genre, actor: Any) -> None:
        """Unlike the wikidata lists, the pop-side list applies to the gold tree, so `LOCAL:` grouping nodes count."""
        root_item_id = self.filter(pk=instance.root.pk).values_list("wikidata_id", flat=True).first()
        if instance.tree_name != CriteriaTreeName.CANONICAL or instance.wikidata_id is None or root_item_id is None:
            return
        if instance.side == CriteriaSide.POP:
            row = {"root_item_id": root_item_id, "pop_child_item_id": instance.wikidata_id}
            upsert_admin_rule(POP_SIDE_LIST, row, actor)
            return
        entries = CurationEntry.objects.filter(
            user=None, list_name=POP_SIDE_LIST, key=KEY_SEPARATOR.join((root_item_id, instance.wikidata_id))
        )
        for entry in entries:
            CurationEntry.objects.delete_instance(entry, actor=actor)

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
        # essential_songs is a many-to-many field: it can't be passed to Model(**kwargs)
        # before the instance has a primary key, so it's set separately after creation.
        essential_songs = kwargs.pop("essential_songs", None)
        instance = super().create(actor=actor, **kwargs)
        if essential_songs is not None:
            self.set_essential_songs(instance, essential_songs)
        return instance

    def set_essential_songs(self, genre: Genre, songs: list[Any]) -> None:
        """The one writer of a genre's ordered essential songs: positions are 1..n in `songs` order."""
        through = self.model.essential_songs.through
        with transaction.atomic(using=self.db):
            through.objects.using(self.db).filter(genre=genre).delete()
            through.objects.using(self.db).bulk_create(
                [through(genre=genre, song=song, position=position) for position, song in enumerate(songs, start=1)]
            )

    @transaction.atomic
    def delete_instance(self, instance: Genre, actor: Any = None) -> None:
        lock_catalogue_sources(using=self.db)
        instance.refresh_from_db(using=self.db)
        self._lock_curation_writes(actor)
        self._release_local_items([instance], actor)
        super().delete_instance(instance, actor=actor)

    @transaction.atomic
    def delete_instances(self, instances: Iterable[Genre], actor: Any = None) -> None:
        instances = list(instances)
        lock_catalogue_sources(using=self.db)
        self._lock_curation_writes(actor)
        self._release_local_items(instances, actor)
        content_type = ContentType.objects.get_for_model(self.model)
        required_root_owners = {i.user_id: i.user for i in instances if self._is_required_root(i)}
        HistoryEntry.objects.bulk_create(
            HistoryEntry(
                user_id=instance.user_id,
                content_type=content_type,
                content_uuid=instance.pk,
                action=HistoryAction.DELETED,
                actor=actor,
                old_value=instance.name,
            )
            for instance in instances
        )
        super().delete_instances(instances, actor=actor)
        for user in required_root_owners.values():
            self.assert_required_roots_present(user)

    def _on_tracks_genre_moved(self, moves: dict[Any, Any], *, actor: Any = None) -> None:
        from grow.model.song.Song import Song

        super()._on_tracks_genre_moved(moves, actor=actor)
        # The deleted genres' playlists go with them while their songs move to the nearest surviving ancestor (or
        # become genreless). Transferring a possibly drifted legacy bucket propagates its error to the surviving
        # parent. The source gate keeps this source count stable. One grouped count, not one per genre.
        songs = Song.objects.filter(user__isnull=True, genre__in=list(moves)).order_by()
        moved_by_target: dict[Any, int] = defaultdict(int)
        for genre_pk, count in songs.values_list("genre").annotate(n=Count("pk")):
            moved_by_target[moves[genre_pk]] += count
        for target, count in moved_by_target.items():
            adjust_direct_songs_count(target, count)
        # Songs left genreless change their search rank. They are re-derived once the tracks are updated, in
        # `_on_before_delete_many`, so remember them while they still point at the deleted genres.
        orphaned = [pk for pk, target in moves.items() if target is None]
        _genreless_song_pks.set(
            list(Song.objects.filter(genre__in=orphaned).order_by().values_list("pk", flat=True)) if orphaned else []
        )

    def _on_before_delete_many(self, instances: list[Genre], *, actor: Any = None) -> None:
        from grow.model.song_search.SongSearch import SongSearch

        super()._on_before_delete_many(instances, actor=actor)
        genreless = _genreless_song_pks.get() or []
        _genreless_song_pks.set(None)
        SongSearch.objects.refresh(genreless)

    @transaction.atomic
    def exclude_instance(self, instance: Genre, category: str, actor: Any = None) -> Genre:
        """Soft-remove a wikidata-backed genre: excluded from the visible tree, protected from
        re-creation/deletion by the next pipeline import, unlike a real DELETE (see
        `AbstractGenreCriteria.is_excluded`)."""
        self._lock_curation_writes(actor)
        was_required_root = self._is_required_root(instance)
        instance.is_excluded = True
        instance.save(update_fields=["is_excluded"])
        if actor is not None and self._is_pipeline_item(instance):
            rule = find_edge_parent_rule(instance.wikidata_id)
            if rule is not None:
                raise self._invalid(
                    "category",
                    f"Remove the {rule.relation} edge {rule.item_id} -> {rule.parent_item_id} first; "
                    "it references this genre",
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
                self._upsert_edge(
                    genre, GenreEdgeRule.Relation.CANONICAL_PARENT, None, actor, exclude_other_parents=True
                )
            HistoryEntry.objects.record(genre, action=HistoryAction.ROOT_ACCEPTED, actor=actor)

    @transaction.atomic
    def update_instance(self, instance: Genre, actor: Any = None, **kwargs) -> Genre:
        self._lock_curation_writes(actor)
        was_required_root = self._is_required_root(instance)
        old_side = instance.side or CriteriaSide.CORE
        summary_changed = "summary" in kwargs and (kwargs["summary"] or "") != (instance.summary or "")
        essential_songs_changed = "essential_songs" in kwargs and [
            song.pk for song in kwargs["essential_songs"]
        ] != self._essential_track_pks(instance)
        new_parent = kwargs.get("parent")
        dropped_secondary_edge = new_parent is not None and self._links_without_new_parent(instance, new_parent, kwargs)
        if summary_changed:
            kwargs["summary_source_url"] = None
        if actor is not None and essential_songs_changed:
            self._write_essential_songs_rules(instance, kwargs["essential_songs"], actor)
        essential_songs = kwargs.pop("essential_songs", None)
        updated = super().update_instance(instance, actor=actor, **kwargs)
        if essential_songs is not None:
            self.set_essential_songs(updated, essential_songs)
        if dropped_secondary_edge:
            self._drop_secondary_add_rule(updated, new_parent.pk, actor)
        if (updated.side or CriteriaSide.CORE) != old_side:
            self._on_side_changed(updated, old_side=old_side, actor=actor)
        if actor is not None:
            if summary_changed:
                self._upsert_rule(updated, "summary_overrides", actor, summary=kwargs["summary"] or "")
            if summary_changed or essential_songs_changed:
                self._lock(updated)
        if was_required_root:
            self.assert_required_roots_present(updated.user)
        return updated

    def _essential_track_pks(self, instance: Genre) -> list[Any]:
        through = self.model.essential_songs.through
        return list(through.objects.filter(genre=instance).order_by("position").values_list("song_id", flat=True))

    def _write_essential_songs_rules(self, instance: Genre, songs: list[Any], actor: Any) -> None:
        """The rows are the genre's whole ordered list: a row per song, and none left for dropped ones."""
        if not self._is_wikidata_item(instance):
            return
        missing = [song for song in songs if song.musicbrainz_recording_id is None]
        if missing:
            raise self._invalid(
                "essential_songs", f"{missing[0].title} has no MusicBrainz id, so no curation rule can name it"
            )
        kept = {str(song.musicbrainz_recording_id) for song in songs}
        stale = CurationEntry.objects.filter(
            user=None, list_name="essential_songs", key__startswith=f"{instance.wikidata_id}{KEY_SEPARATOR}"
        )
        for entry in stale:
            if entry.key.split(KEY_SEPARATOR)[1] not in kept:
                CurationEntry.objects.delete_instance(entry, actor=actor)
        for position, song in enumerate(songs, start=1):
            upsert_admin_rule(
                "essential_songs",
                {
                    "item_id": instance.wikidata_id,
                    "musicbrainz_recording_id": str(song.musicbrainz_recording_id),
                    "position": str(position),
                },
                actor,
            )

    @transaction.atomic
    def set_secondary_parent(self, instance: Genre, parent: Genre, *, add: bool, actor: Any) -> Genre:
        self._lock_curation_writes(actor)
        if parent.pk == instance.pk:
            raise self._invalid("parent", "A genre can't be its own secondary parent")
        if parent.pk == instance.parent_id:
            raise self._invalid("parent", "The main parent can't also be a secondary parent")
        if instance.wikidata_id is None or parent.wikidata_id is None:
            raise self._invalid("parent", "Secondary parents are only recorded between wikidata-backed genres")
        others = [other for other in instance.secondary_parents.all() if other.pk != parent.pk]
        updated = self.update_instance(instance, actor=actor, secondary_parents=[*others, parent] if add else others)
        self._upsert_edge(
            instance,
            GenreEdgeRule.Relation.SECONDARY_PARENT,
            parent.wikidata_id,
            actor,
            action=GenreEdgeRule.Action.ADD if add else GenreEdgeRule.Action.REMOVE,
        )
        self._lock(updated)
        return updated

    @staticmethod
    def _songs_of(genre: Genre):
        from grow.model.song.Song import Song

        return Song.objects.filter(genre=genre)

    def alias_counts(self, source: Genre, target: Genre) -> dict[str, int]:
        """What aliasing `source` onto `target` moves; a 400 when the pair isn't an allowed alias."""
        if source.wikidata_id is not None:
            raise self._invalid("genre", "Only a genre without a wikidata id can be an alias")
        if target.wikidata_id is None:
            raise self._invalid("target", "The alias target must have a wikidata id")
        if source.descendants_rels.filter(descendant=target).exists():
            raise self._invalid("target", "The alias target can't be a descendant of the alias; it would loop the tree")
        return {
            "songs": self._songs_of(source).count(),
            "essential_songs": source.essential_songs.count(),
            "children": self.filter(parent=source).count(),
        }

    @transaction.atomic
    def alias_instance(self, source: Genre, target: Genre, actor: Any) -> Genre:
        """Merges a MusicBrainz-only genre into the wikidata genre it names: the rule lets the next import match
        them, and the source's songs, essential songs and children move to the target before it is deleted."""
        self._lock_curation_writes(actor)
        self.alias_counts(source, target)
        upsert_admin_rule(
            "genre_alias",
            {"musicbrainz_genre_name": source.name.lower(), "wikidata_genre_name": target.name},
            actor,
        )
        for song in list(self._songs_of(source)):
            type(song).objects.update_instance(song, actor=actor, genre=target)
        pks = self._essential_track_pks(target)
        pks += [pk for pk in self._essential_track_pks(source) if pk not in pks]
        songs = self.model.essential_songs.field.related_model.objects.in_bulk(pks)
        self.update_instance(target, actor=actor, essential_songs=[songs[pk] for pk in pks])
        for child in list(self.filter(parent=source)):
            self.update_instance(child, actor=actor, parent=target)
        self.delete_instance(source, actor=actor)
        self._lock(target)
        return target

    def region_lexicon(self, item_ids: set[str]) -> list[dict[str, Any]]:
        """The app-wide genres with these Wikidata ids, in one query, for clients that search them in memory. Genres
        under an unaccepted root are left out, like they are from search."""
        return list(
            self.filter(user__isnull=True, wikidata_id__in=item_ids)
            .exclude(root__genre__is_unaccepted_root=True)
            .values(
                "uuid",
                "wikidata_id",
                "tree_name",
                "is_umbrella",
                name=F(Fields.NAME_INTERNAL),
                genre_playlist_uuid=F("criteria_playlist__uuid"),
                views_count=Coalesce(F("criteria_playlist__views_count"), 0),
            )
            .order_by("wikidata_id", "uuid")
        )

    def search(self, query: str, limit: int, tree_name: str | None = None) -> list[dict[str, Any]]:
        """Canonical genres of both trees (or of `tree_name`) whose folded name trigram-matches `query`, best first:
        exact, then prefix, then fuzzy, ties broken by similarity then playlist views. One indexed query, no
        hydration. Genres under an unaccepted root are left out, like they are from the tree page."""
        with transaction.atomic(), connection.cursor() as cursor:
            folded_query = fold_query(cursor, query)
            queryset = self.filter(user__isnull=True, folded_name__trigram_word_similar=folded_query).exclude(
                root__genre__is_unaccepted_root=True
            )
            if tree_name is not None:
                queryset = queryset.filter(tree_name=tree_name)
            return list(
                queryset.values(
                    "uuid",
                    "wikidata_id",
                    "tree_name",
                    "is_umbrella",
                    name=F(Fields.NAME_INTERNAL),
                    genre_playlist_uuid=F("criteria_playlist__uuid"),
                    root_uuid=F("root__uuid"),
                    root_name=F(f"root__{Fields.NAME_INTERNAL}"),
                    views_count=Coalesce(F("criteria_playlist__views_count"), 0),
                    rank=match_rank("folded_name", folded_query),
                    score=TrigramWordSimilarity(folded_query, "folded_name"),
                ).order_by("-rank", "-score", "-views_count", "uuid")[:limit]
            )
