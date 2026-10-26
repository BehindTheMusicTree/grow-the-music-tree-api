from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from grow.artist.bulk_import.ArtistImportStaging import ArtistImportStaging
from grow.artist.bulk_import.merge import merge_artist_import_run
from grow.artist.bulk_import.part_loader import load_part
from grow.filtering.set.artist.ArtistFilterSet import ArtistFilterSet
from grow.model.artist.Artist import Artist
from grow.model.import_run.ImportRun import ImportRun
from grow.serializer.model.artist.detailed import ArtistDetailedSerializer
from grow.serializer.model.artist.search import ArtistSearchQuerySerializer, ArtistSearchResultSerializer
from grow.serializer.model.artist.simple import ArtistSimpleSerializer
from grow.view.viewset.GrowModelViewSet import GrowModelViewSet
from grow.view.viewset.mixin.BulkImportRunMixin import bulk_import_run_actions


class ArtistViewSet(GrowModelViewSet[Artist]):
    throttle_scope = "artist-search"

    def __init__(self, **kwargs):
        super().__init__(
            model_class=Artist,
            filterset_class=ArtistFilterSet,
            simple_serializer_class=ArtistSimpleSerializer,
            detailed_serializer_class=ArtistDetailedSerializer,
            **kwargs,
        )

    def list(self, *args, **kwargs):
        return self._handle_list()

    def retrieve(self, *args, **kwargs):
        return self._handle_retrieve()

    def destroy(self, *args, **kwargs):
        return self._handle_destroy()

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
        throttle_classes=[ScopedRateThrottle],
    )
    def search(self, request):
        query = ArtistSearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        artists = Artist.objects.search(query.validated_data["q"], query.validated_data["limit"])
        return Response(ArtistSearchResultSerializer(artists, many=True).data)

    (
        create_import_run,
        upload_import_run_part,
        upload_import_run_deletions,
        commit_import_run,
        import_run_status,
    ) = bulk_import_run_actions(
        "", ImportRun.Kind.ARTISTS, ArtistImportStaging, load_part, merge_artist_import_run, "musicbrainz_artist_id"
    )
