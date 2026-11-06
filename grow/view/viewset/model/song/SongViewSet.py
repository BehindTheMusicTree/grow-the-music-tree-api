from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from the_music_tree_api_kit.serializer.SerializerType import SerializerType

from grow.filtering.set.song.SongFilterSet import SongFilterSet
from grow.model.import_run.ImportRun import ImportRun
from grow.model.song.Song import Song
from grow.model.song.SongCurationManager import SongCurationManager
from grow.model.song_search.SongSearch import SongSearch
from grow.search.cache import SearchCache, cached_search
from grow.serializer.model.song.input import SongAssignGenreSerializer, SongYoutubePatchSerializer
from grow.serializer.model.song.output.detailed import SongDetailedSerializer
from grow.serializer.model.song.output.full import SongFullSerializer
from grow.serializer.model.song.search import SongSearchQuerySerializer, SongSearchResultSerializer
from grow.track.bulk_import.merge import merge_song_import_run
from grow.track.bulk_import.part_loader import load_part
from grow.track.bulk_import.SongImportStaging import SongImportStaging
from grow.view.pagination.OptionalTotalPagination import (
    CURSOR_ORDERING,
    OptionalTotalPagination,
    wants_cursor,
    wants_no_total,
)
from grow.view.permission.IsAdmin import IsAdmin
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet
from grow.view.viewset.mixin.BulkImportRunMixin import bulk_import_run_actions
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin
from grow.youtube_regions import viewer_country


class SongViewSet(HistoryActionMixin, GrowModelViewSet[Song]):
    pagination_class = OptionalTotalPagination
    throttle_scope = "song-search"

    def __init__(self, **kwargs):
        super().__init__(
            model_class=Song,
            filterset_class=SongFilterSet,
            simple_serializer_class=SongDetailedSerializer,
            detailed_serializer_class=SongFullSerializer,
            **kwargs,
        )

    def _get_detailed_serializer(self, instance):
        serializer = super()._get_detailed_serializer(instance)
        serializer.context.update(self.get_serializer_context())
        return serializer

    def _get_paginated_list_response(self, queryset, serializer_type=SerializerType.SIMPLE, status_code=200):
        serializer_class = self._require_serializer(serializer_type)
        queryset = self._eager_load(serializer_class, self.filter_queryset(queryset))
        page = self.paginate_queryset(queryset)
        serializer = serializer_class(
            page if page is not None else queryset, many=True, context=self.get_serializer_context()
        )
        if page is None:
            return Response(serializer.data, status=status_code)
        response = self.get_paginated_response(serializer.data)
        response.status_code = status_code
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["X-Playback-Country"] = viewer_country(request) or "unknown"
        return response

    def list(self, *args, **kwargs):
        # Genreless songs are stored for later linking but have no place in the tree.
        queryset = self.get_queryset().filter(genre__isnull=False)
        if wants_cursor(self.request):
            params = self.request.query_params
            if "genre" not in params or "ordering" in params or "from" in params:
                raise ParseError("Cursor pagination requires `genre` and supports neither `ordering` nor `from`.")
            # (genre, uuid) matches the track index, so each page is one range scan instead of a sort of the subtree.
            queryset = queryset.order_by(*CURSOR_ORDERING)
        elif wants_no_total(self.request):
            queryset = queryset.order_by("pk")
        return self._get_paginated_list_response(queryset)

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def destroy(self, *args, **kwargs):
        return self._handle_destroy()

    def partial_update(self, request, *args, **kwargs):
        song = self.get_object()
        serializer = SongYoutubePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unknown = set(request.data) - set(serializer.fields)
        if unknown:
            raise ValidationError(dict.fromkeys(sorted(unknown), "Not editable"))
        updated = SongCurationManager().update_youtube(song, serializer.validated_data, request.user)
        return Response(self._get_detailed_serializer(updated).data)

    @action(detail=False, methods=["post"], url_path="assign-genre", permission_classes=[IsAdmin])
    def assign_genre(self, request):
        serializer = SongAssignGenreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        previous = SongCurationManager().assign_genre(
            serializer.validated_data["songs"], serializer.validated_data["genre"], request.user
        )
        return Response({"previous": previous})

    @action(
        detail=False,
        methods=["get"],
        authentication_classes=[],
        permission_classes=[AllowAny],
        throttle_classes=[ScopedRateThrottle],
    )
    def search(self, request):
        query = SongSearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        payload = cached_search(
            SearchCache.SONGS,
            params["q"],
            (params["limit"], params["genre"], params["playable"], viewer_country(request)),
            lambda: (
                SongSearchResultSerializer(
                    SongSearch.objects.search(
                        params["q"], params["limit"], params["genre"], params["playable"], viewer_country(request)
                    ),
                    many=True,
                    context=self.get_serializer_context(),
                ).data
            ),
        )
        return Response(payload)

    (
        create_import_run,
        upload_import_run_part,
        upload_import_run_deletions,
        commit_import_run,
        import_run_status,
    ) = bulk_import_run_actions(
        "songs/", ImportRun.Kind.SONGS, SongImportStaging, load_part, merge_song_import_run, "musicbrainz_recording_id"
    )
