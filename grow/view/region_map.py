import gzip

from django.http import HttpRequest, HttpResponse, HttpResponseNotModified, JsonResponse
from django.utils.http import parse_etags
from django.views import View
from rest_framework import viewsets

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.model.import_run.ImportRun import ImportRun
from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from grow.region_map.bulk_import.merge import merge_region_map_import_run
from grow.region_map.bulk_import.part_loader import load_part
from grow.region_map.bulk_import.RegionMapFileStaging import RegionMapFileStaging
from grow.view.viewset.mixin.BulkImportRunMixin import bulk_import_run_actions


class RegionMapViewSet(viewsets.ViewSet):
    """Pipeline import of the region map: one full run uploads the index and every GeoJSON file, one line each."""

    authentication_classes = [GoogleIdTokenAuthentication, ApiKeyAuthentication]

    (
        create_import_run,
        upload_import_run_part,
        upload_import_run_deletions,
        commit_import_run,
        import_run_status,
    ) = bulk_import_run_actions(
        "", ImportRun.Kind.REGION_MAP, RegionMapFileStaging, load_part, merge_region_map_import_run, "path"
    )


def _file_response(
    request: HttpRequest, sha256: str, content_type: str, cache_control: str
) -> HttpResponse | HttpResponseNotModified:
    """
    The stored gzip body as-is, inflated only for a client that does not accept gzip. A plain Django view: DRF content
    negotiation would refuse an `Accept: application/geo+json` request.
    """
    etag = f'"{sha256}"'
    headers = {"ETag": etag, "Cache-Control": cache_control, "Vary": "Accept-Encoding"}
    if etag in (e.removeprefix("W/") for e in parse_etags(request.headers.get("If-None-Match", ""))):
        return HttpResponseNotModified(headers=headers)
    body = RegionMapFile.objects.filter(pk=sha256).values_list("body", flat=True).first()
    if body is None:
        return JsonResponse({"detail": "No region map file has this sha256."}, status=404)
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        return HttpResponse(bytes(body), content_type=content_type, headers={**headers, "Content-Encoding": "gzip"})
    return HttpResponse(gzip.decompress(body), content_type=content_type, headers=headers)


class RegionMapIndexView(View):
    """The latest region map index, public, revalidated by its checksum. Its `files` map gives each file's URL hash."""

    def get(self, request: HttpRequest) -> HttpResponse | HttpResponseNotModified:
        snapshot = RegionMapSnapshot.objects.first()
        if snapshot is None:
            return JsonResponse({"detail": "No region map snapshot has been imported yet."}, status=404)
        return _file_response(request, snapshot.checksum, "application/json", "no-cache")


class RegionMapFileView(View):
    """One region map GeoJSON file by content hash: its URL never changes meaning, so it is cached for good."""

    def get(self, request: HttpRequest, sha256: str) -> HttpResponse | HttpResponseNotModified:
        return _file_response(request, sha256, "application/geo+json", "public, max-age=31536000, immutable")
