from django.contrib.contenttypes.models import ContentType
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from grow.model.history.HistoryEntry import HistoryEntry
from grow.serializer.model.history.output.detailed import HistoryEntryDetailedSerializer


class HistoryActionMixin:
    @action(detail=True, methods=["get"])
    def history(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        queryset = HistoryEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(self.model_class),
            content_uuid=instance.uuid,
        ).order_by("created_on")
        serializer = HistoryEntryDetailedSerializer(queryset, many=True)
        return Response(data=serializer.data)
