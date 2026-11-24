from typing import Any

from drf_spectacular.views import SpectacularAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response


class CachedSchemaView(SpectacularAPIView):
    """
    Public schema endpoint that generates the schema once per process: the URLconf does not change at runtime, and
    generation walks every route (and logs its warnings), which an anonymous caller must not be able to trigger on
    every request. The API is not versioned, so the cache has a single entry whatever `?version=` says.
    """

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    _schema: dict[str, Any] | None = None

    def _get_schema_response(self, request: Request) -> Response:
        cls = type(self)
        if cls._schema is None:
            cls._schema = self.generator_class(urlconf=self.urlconf, patterns=self.patterns).get_schema(
                request=request, public=self.serve_public
            )
        return Response(
            data=cls._schema,
            headers={"Content-Disposition": f'inline; filename="{self._get_filename(request, None)}"'},
        )
