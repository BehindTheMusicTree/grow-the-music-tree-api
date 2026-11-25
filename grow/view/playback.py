from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from grow.serializer.schema.runs import PlaybackContextSerializer
from grow.youtube_regions import viewer_country


class PlaybackContextView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses=PlaybackContextSerializer)
    def get(self, request):
        return Response({"country": viewer_country(request)}, headers={"Cache-Control": "private, no-store"})
