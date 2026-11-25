from uuid import UUID

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ParseError, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.utils.urls import replace_query_param
from the_music_tree_api_kit.serializer.SerializerType import SerializerType
from the_music_tree_api_kit.view.pagination.PaginatedResponseFields import PaginatedResponseFields
from the_music_tree_genre_kit.genre_graph.models import GenreGraphDataset
from the_music_tree_genre_kit.genre_graph.storage import graph_read_transaction

from grow.artist_song import page as artist_song_page
from grow.filtering.set.song.SongFilterSet import SongFilterSet
from grow.genre_graph.selection import require_reference_graph
from grow.genre_graph.service import DATASET_KEY
from grow.genre_graph.snapshot import graph_snapshot
from grow.model.artist_song.ArtistSong import ArtistSong
from grow.model.import_run.ImportRun import ImportRun
from grow.model.song.Song import Song
from grow.model.song.SongCurationManager import SongCurationManager
from grow.model.song_search.SongSearch import SongSearch
from grow.search.cache import SearchCache, cached_search
from grow.serializer.model.song.input import (
    SongAssignGenreSerializer,
    SongAssignGenreUndoSerializer,
    SongYoutubePatchSerializer,
)
from grow.serializer.model.song.output.detailed import SongDetailedSerializer
from grow.serializer.model.song.output.full import SongFullSerializer
from grow.serializer.model.song.search import SongSearchQuerySerializer, SongSearchResultSerializer
from grow.serializer.schema.song import SongAssignGenreResultSerializer
from grow.track.bulk_import.merge import merge_song_import_run
from grow.track.bulk_import.part_loader import load_part
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging
from grow.track.bulk_import.SongImportStaging import SongImportStaging
from grow.view.pagination.OptionalTotalPagination import (
    CURSOR_PARAM,
    OptionalTotalPagination,
    next_cursor_link,
    wants_cursor,
    wants_total,
)
from grow.view.pagination.song_cursor import SongCursor, cursor_ordering
from grow.view.permission.IsAdmin import IsAdmin
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet
from grow.view.viewset.mixin.BulkImportRunMixin import assignment_part_upload_action, bulk_import_run_actions
from grow.view.viewset.model.HistoryActionMixin import HistoryActionMixin
from grow.youtube_regions import viewer_country

ARTIST_CURSOR_PARAMS = {"artist", "ordering", "cursor", "pagination", "page_size", "with_total", "from"}
ARTIST_PAGE_PARAMS = {"page", "playable", "genre", "coverage", "subgenres"}


@extend_schema_view(
    list=extend_schema(
        responses=OpenApiResponse(
            SongDetailedSerializer(many=True),
            description="Headers `X-Genre-Graph-Revision` and `X-Genre-Membership-Revision` carry the graph read.",
        )
    ),
    destroy=extend_schema(responses={status.HTTP_204_NO_CONTENT: None}),
    partial_update=extend_schema(request=SongYoutubePatchSerializer, responses=SongFullSerializer),
    assign_genre=extend_schema(request=SongAssignGenreSerializer, responses=SongAssignGenreResultSerializer),
    undo_assign_genre=extend_schema(
        request=SongAssignGenreUndoSerializer, responses={status.HTTP_204_NO_CONTENT: None}
    ),
    search=extend_schema(
        parameters=[SongSearchQuerySerializer], responses=SongSearchResultSerializer(many=True), filters=False
    ),
)
class SongViewSet(HistoryActionMixin, GrowModelViewSet[Song]):
    pagination_class = OptionalTotalPagination
    throttle_scope = "song-search"
    upload_assignment_part = assignment_part_upload_action("songs/")

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
        try:
            with graph_read_transaction(key=DATASET_KEY) as dataset:
                response = self._list_graph_songs()
                response["X-Genre-Graph-Revision"] = str(dataset.revision)
                response["X-Genre-Membership-Revision"] = str(dataset.membership_revision)
                return response
        except GenreGraphDataset.DoesNotExist:
            require_reference_graph()
            raise

    def _list_graph_songs(self):
        # Songs without semantic attributions remain available for later curation.
        queryset = self.get_queryset()
        params = self.request.query_params
        cursor_mode = wants_cursor(self.request)
        if not cursor_mode and CURSOR_PARAM in params:
            raise ParseError("`cursor` and `page` are mutually exclusive.")
        if "artist" in params and not cursor_mode:
            return self._list_numbered_artist_songs(queryset)
        if self._reads_artist_index():
            return self._list_artist_songs(queryset)
        return self._get_paginated_list_response(queryset)

    def _reads_artist_index(self) -> bool:
        """The `ArtistSong` index serves a plain artist list; any other filter or ordering takes the generic keyset.

        Every page of a list must take the same path: `next` only adds `cursor` and drops `from` and `with_total`,
        all of which the index accepts.
        """
        params = self.request.query_params
        return (
            wants_cursor(self.request)
            and "artist" in params
            and set(params) <= ARTIST_CURSOR_PARAMS
            and cursor_ordering(params) in artist_song_page.ORDERINGS
        )

    def _list_numbered_artist_songs(self, queryset):
        unsupported = set(self.request.query_params) - ((ARTIST_CURSOR_PARAMS - {CURSOR_PARAM}) | ARTIST_PAGE_PARAMS)
        if unsupported:
            raise ParseError(f"Unsupported artist song filters: {sorted(unsupported)}.")
        response = self._get_paginated_list_response(queryset)
        if response.data[PaginatedResponseFields.PAGE] == 2:
            # DRF omits page=1 from the previous link, but here it selects numbered pagination.
            previous_key = PaginatedResponseFields.PREVIOUS
            response.data[previous_key] = replace_query_param(response.data[previous_key], "page", 1)
        return response

    def _list_artist_songs(self, queryset):
        """Read one indexed cursor page of an artist's songs."""
        params = self.request.query_params
        with_total = wants_total(self.request)
        ordering = cursor_ordering(params)
        if ordering not in artist_song_page.ORDERINGS:
            raise ParseError(f"`ordering` with `artist` must be one of {list(artist_song_page.ORDERINGS)}.")
        try:
            artist_id = UUID(params["artist"])
        except ValueError as error:
            raise ParseError("Invalid artist.") from error
        raw_cursor = params.get("cursor")
        cursor = SongCursor.decode(raw_cursor, ordering) if raw_cursor else None
        from_id = None
        if "from" in params:
            if "cursor" in params:
                raise ParseError("`from` and `cursor` are mutually exclusive.")
            try:
                from_id = UUID(params["from"])
            except ValueError as error:
                raise ParseError("Invalid `from`.") from error
        ArtistSong.objects.require_ready()
        start = None
        if from_id:
            start = artist_song_page.anchor(artist_id, ordering, from_id)
            if start is None:
                raise NotFound(f"Song {from_id} is not in this list.")
        total = artist_song_page.count(artist_id, ordering, start) if with_total else None
        size = self.paginator.get_page_size(self.request)
        found = artist_song_page.page(artist_id, ordering, start or cursor, size + 1, inclusive=start is not None)
        has_next = len(found) > size
        found = found[:size]
        serializer_class = self._require_serializer(SerializerType.SIMPLE)
        songs = {
            song.pk: song
            for song in self._eager_load(serializer_class, queryset.filter(pk__in=[song_id for song_id, _ in found]))
        }
        data = serializer_class(
            [songs[song_id] for song_id, _ in found if song_id in songs],
            many=True,
            context=self.get_serializer_context(),
        ).data
        next_link = next_cursor_link(self.request, found[-1][1].encode()) if has_next else None
        return Response(
            {
                PaginatedResponseFields.OVERALL_TOTAL: total,
                PaginatedResponseFields.NEXT: next_link,
                PaginatedResponseFields.PREVIOUS: None,
                PaginatedResponseFields.RESULTS: data,
                PaginatedResponseFields.PAGE: None,
                PaginatedResponseFields.PAGE_SIZE: size,
                PaginatedResponseFields.TOTAL_PAGES: None,
            }
        )

    @graph_snapshot
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
        previous, undo_token = SongCurationManager().assign_genre(
            serializer.validated_data["songs"], serializer.validated_data["genre"], request.user
        )
        return Response({"previous": previous, "undo_token": undo_token})

    @action(detail=False, methods=["post"], url_path="assign-genre/undo", permission_classes=[IsAdmin])
    def undo_assign_genre(self, request):
        serializer = SongAssignGenreUndoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        SongCurationManager().undo_assign_genre(serializer.validated_data["undo_token"], request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=False,
        methods=["get"],
        authentication_classes=[],
        permission_classes=[AllowAny],
        throttle_classes=[ScopedRateThrottle],
        pagination_class=None,
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
        "songs/",
        ImportRun.Kind.SONGS,
        SongImportStaging,
        load_part,
        merge_song_import_run,
        "musicbrainz_recording_id",
        extra_staging_models=(SongAssignmentStaging,),
    )
