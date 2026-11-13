import json
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import QueryDict
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from the_music_tree_api_kit.private.get_request_owner import get_request_owner
from the_music_tree_genre_kit.playlist.Playlist import Playlist
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.serializer import CriteriaTreeImportSerializer

from grow.bulk_import.analyze import analyze
from grow.bulk_import.BulkImportRun import GENRE_TREES_KIND, BulkImportRun
from grow.bulk_import.lifecycle import queue_attempt
from grow.genre_tree.bulk_import.GenreTreeImportPayload import GenreTreeImportPayload
from grow.genre_tree.bulk_import.merge import (
    CURATION_EXPORTED_ON,
    TREE_IMPORT_MODELS,
    TREE_IMPORT_RUN_KINDS,
    merge_genre_trees_import_run,
    node_count,
    parse_curation_exported_on,
)
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.criteria.Criteria import Criteria
from grow.model.criteria.lineage_rel.CriteriaLineageRel import CriteriaLineageRel
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.import_run.ImportRun import ImportRun
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.playlist.GenreCatalogueCount import GenreCatalogueCount
from grow.model.song.SongCurationManager import SongCurationManager
from grow.search.cache import SearchCache, cached_search
from grow.serializer.model.criteria.children.genre.input.alias_of import GenreAliasOfSerializer
from grow.serializer.model.criteria.children.genre.input.exclude import GenreExcludeSerializer
from grow.serializer.model.criteria.children.genre.input.name_conflict_validate import (
    GenreNameConflictValidateSerializer,
)
from grow.serializer.model.criteria.children.genre.input.post import GenrePostSerializer
from grow.serializer.model.criteria.children.genre.input.put import GenrePutSerializer
from grow.serializer.model.criteria.children.genre.input.unaccepted_root_accept import (
    GenreUnacceptedRootAcceptSerializer,
)
from grow.serializer.model.criteria.children.genre.output.detailed import GenreDetailedSerializer
from grow.serializer.model.criteria.children.genre.output.name_conflict_group import GenreNameConflictGroupSerializer
from grow.serializer.model.criteria.children.genre.output.simple import GenreSimpleSerializer
from grow.serializer.model.criteria.children.genre.search import GenreSearchQuerySerializer, GenreSearchResultSerializer
from grow.serializer.model.song.output.without_playlists import SongWithoutPlaylistsSerializer
from grow.view.permission.IsAdmin import IsAdmin
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin
from grow.view.viewset.mixin.BulkImportRunMixin import enqueue_merge, import_run_status_action
from grow.view.viewset.model.criteria.CriteriaViewSet import CriteriaViewSet
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin

# Bump when the search payload shape changes: the tree version token only moves on genre writes, so results cached
# in the old shape would otherwise be served until the next write or TTL.
GENRE_SEARCH_PAYLOAD_VERSION = 2


def _is_json_object(data: Any) -> bool:
    return isinstance(data, dict) and not isinstance(data, QueryDict)


def _pop_curation_exported_on(tree_file: Any) -> Any:
    """The raw curation export of a Gold tree file, popped so the tree serializer sees only its own fields."""
    return tree_file.pop(CURATION_EXPORTED_ON, None) if _is_json_object(tree_file) else None


def _curation_exported_on(request: Request, state: CurationSyncState) -> datetime:
    return parse_curation_exported_on(_pop_curation_exported_on(request.data), state)


class GenreViewSet(HistoryActionMixin, CriteriaViewSet):
    throttle_scope = "genre-search"

    def __init__(self, **kwargs):
        from grow.filtering.set.criteria.children.genre.GenreFilterSet import GenreFilterSet

        super().__init__(
            model_class=Genre,
            simple_serializer_class=GenreSimpleSerializer,
            detailed_serializer_class=GenreDetailedSerializer,
            filterset_class=GenreFilterSet,
            create_serializer_class=GenrePostSerializer,
            update_serializer_class=GenrePutSerializer,
            **kwargs,
        )

    @action(
        detail=False,
        methods=["get"],
        authentication_classes=[],
        permission_classes=[AllowAny],
        throttle_classes=[ScopedRateThrottle],
    )
    def search(self, request: Request) -> Response:
        query = GenreSearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        q, limit, tree_name = (query.validated_data[k] for k in ("q", "limit", "tree_name"))
        # The tree version token is regenerated by DB triggers on every genre or playlist write, so a key built
        # on it can't serve results from before an import, curation, or admin edit.
        payload = cached_search(
            SearchCache.GENRES,
            q,
            (GENRE_SEARCH_PAYLOAD_VERSION, limit, tree_name, GenreTreeVersion.current_token()),
            lambda: GenreSearchResultSerializer(Genre.objects.search(q, limit, tree_name), many=True).data,
        )
        return Response(payload)

    @action(detail=False, methods=["post"], url_path="tree/import", permission_classes=[IsPipelineOrAdmin])
    def import_tree(self, request):
        is_pipeline = request.auth.role == "pipeline"
        with transaction.atomic():
            if is_pipeline:
                state = CurationSyncState.load()
                state.applied_export_on = _curation_exported_on(request, state)
            response = super().import_tree(request)
            Genre.objects.assert_required_roots_present(get_request_owner(request))
            analyze(TREE_IMPORT_MODELS)
            if is_pipeline:
                state.save(update_fields=["applied_export_on"])
                ImportRun.objects.create(
                    kind=TREE_IMPORT_RUN_KINDS[request.data[Fields.TREE_NAME]],
                    count=node_count(request.data[Fields.TREE]),
                )

        return response

    import_run_status = import_run_status_action("trees/", GENRE_TREES_KIND, merge_genre_trees_import_run)

    @action(detail=False, methods=["post"], url_path="trees/import-runs", permission_classes=[IsPipelineOrAdmin])
    def import_trees(self, request):
        """
        Imports several trees in one asynchronous merge, so a genre that moved between the canonical and the regional
        tree keeps its pk and songs. The body is `{trees: [<Gold tree file>]}`, each entry exactly what `tree/import/`
        takes. A pipeline entry carries its own `curationExportedOn` (popped like there), equal across entries.
        """
        owner = get_request_owner(request)
        record = request.auth.role == "pipeline"
        body = request.data if _is_json_object(request.data) else {}
        unknown = sorted(set(body) - {"trees"})
        if unknown:
            raise ValidationError(dict.fromkeys(unknown, "Unknown field: only `trees` is accepted at the top level"))
        entries = body.get("trees")
        exports = []
        if record and isinstance(entries, list):
            state = CurationSyncState.load()
            exports = [_pop_curation_exported_on(entry) for entry in entries]
            parsed = {parse_curation_exported_on(value, state) for value in exports}
            if len(parsed) > 1:
                raise ValidationError({"trees": "Mixed curation exports: every tree needs the same curationExportedOn"})
        serializer = CriteriaTreeImportSerializer(data=entries, many=True)
        serializer.is_valid(raise_exception=True)
        trees = [dict(tree) for tree in serializer.validated_data]
        if not trees:
            raise ValidationError({"trees": "At least one tree is required"})
        exported_on = exports[0] if exports else None
        payload = {"trees": trees, CURATION_EXPORTED_ON: exported_on}
        with transaction.atomic():
            # Drop the runs of an earlier merge django-q killed without cleanup (see bulk_import_run_actions).
            stale = BulkImportRun.objects.filter(
                kind=GENRE_TREES_KIND,
                committed_on__lt=timezone.now() - timedelta(seconds=2 * settings.Q_CLUSTER["timeout"]),
            )
            GenreTreeImportPayload.objects.filter(run_id__in=stale.values("pk")).delete()
            stale.delete()
            now = timezone.now()
            run = BulkImportRun.objects.create(
                kind=GENRE_TREES_KIND, committed_on=now, user_id=owner and owner.pk, record=record
            )
            GenreTreeImportPayload.objects.create(run_id=run.pk, payload=json.loads(json.dumps(payload, default=str)))
            attempt = queue_attempt(run)
        enqueue_merge(merge_genre_trees_import_run, run, attempt)
        return Response({"task_id": attempt.task_id}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def exclude(self, request: Request, *args, **kwargs) -> Response:
        genre = self.get_object()
        input_serializer = GenreExcludeSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        instance = Genre.objects.exclude_instance(
            genre, input_serializer.validated_data["category"], **self._get_manager_write_kwargs(request)
        )
        return self._detailed(instance)

    @action(detail=False, methods=["get"], url_path="name-conflicts")
    def name_conflicts(self, request: Request) -> Response:
        groups = Genre.objects.get_name_conflict_groups(get_request_owner(request))
        return Response(data=GenreNameConflictGroupSerializer(groups, many=True).data)

    @action(detail=False, methods=["post"], url_path="name-conflicts/validate")
    def validate_name_conflicts(self, request: Request) -> Response:
        serializer = GenreNameConflictValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        Genre.objects.validate_name_conflict_group(
            get_request_owner(request),
            {genre["uuid"]: genre["name"] for genre in serializer.validated_data["genres"]},
            **self._get_manager_write_kwargs(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="unaccepted-roots")
    def unaccepted_roots(self, request: Request) -> Response:
        genres = Genre.objects.get_unaccepted_roots(get_request_owner(request))
        return Response(data=GenreSimpleSerializer(genres, many=True).data)

    @action(detail=False, methods=["post"], url_path="unaccepted-roots/accept")
    def accept_unaccepted_roots(self, request: Request) -> Response:
        serializer = GenreUnacceptedRootAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        Genre.objects.accept_roots(
            get_request_owner(request),
            [genre["uuid"] for genre in serializer.validated_data["genres"]],
            **self._get_manager_write_kwargs(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _genre_by_uuid(self, uuid) -> Genre:
        return get_object_or_404(self.get_queryset(), uuid=uuid)

    def _detailed(self, genre: Genre) -> Response:
        return Response(data=self._get_detailed_serializer(genre).data)

    @action(detail=True, methods=["get"], url_path="link-suggestions", permission_classes=[IsAdmin])
    def link_suggestions(self, request: Request, *args, **kwargs) -> Response:
        songs = SongCurationManager.link_suggestions(self.get_object())
        data = SongWithoutPlaylistsSerializer(songs, many=True, context=self.get_serializer_context()).data
        return Response(
            [{**item, "shared_artists": song.shared_artists} for item, song in zip(data, songs, strict=True)]
        )

    @action(
        detail=True,
        methods=["post", "delete"],
        url_path=r"secondary-parents/(?P<parent_uuid>[0-9a-f-]+)",
        permission_classes=[IsAdmin],
    )
    def secondary_parent(self, request: Request, parent_uuid: str, *args, **kwargs) -> Response:
        genre = Genre.objects.set_secondary_parent(
            self.get_object(),
            self._genre_by_uuid(parent_uuid),
            add=request.method == "POST",
            **self._get_manager_write_kwargs(request),
        )
        return self._detailed(genre)

    @action(detail=True, methods=["post"], url_path="alias-of", permission_classes=[IsAdmin])
    def alias_of(self, request: Request, *args, **kwargs) -> Response:
        serializer = GenreAliasOfSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = Genre.objects.alias_instance(
            self.get_object(),
            self._genre_by_uuid(serializer.validated_data["target"]),
            **self._get_manager_write_kwargs(request),
        )
        return self._detailed(target)

    @action(detail=True, methods=["get"], url_path="alias-of/preview", permission_classes=[IsAdmin])
    def alias_of_preview(self, request: Request, *args, **kwargs) -> Response:
        serializer = GenreAliasOfSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        counts = Genre.objects.alias_counts(self.get_object(), self._genre_by_uuid(serializer.validated_data["target"]))
        return Response(counts)
