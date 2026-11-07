import gzip
import json

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, HttpResponseNotModified, JsonResponse
from django.utils.http import parse_etags
from django.views import View
from rest_framework import viewsets

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.import_run.ImportRun import ImportRun
from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from grow.region_map.bulk_import.merge import merge_region_map_import_run
from grow.region_map.bulk_import.part_loader import load_part
from grow.region_map.bulk_import.RegionMapFileStaging import RegionMapFileStaging
from grow.region_map.genre_lexicon import genre_item_ids, serialize_lexicon
from grow.view.viewset.mixin.BulkImportRunMixin import bulk_import_run_actions


class RegionMapViewSet(viewsets.ViewSet):
    """Pipeline import of the region map: one full run uploads the index, one line."""

    authentication_classes = [GoogleIdTokenAuthentication, ApiKeyAuthentication]

    (
        create_import_run,
        upload_import_run_part,
        upload_import_run_deletions,
        commit_import_run,
        import_run_status,
    ) = bulk_import_run_actions(
        "",
        ImportRun.Kind.REGION_MAP,
        RegionMapFileStaging,
        load_part,
        merge_region_map_import_run,
        "path",
        modes=(BulkImportRun.Mode.FULL,),
    )


def _accepts_gzip(accept_encoding: str) -> bool:
    """RFC 9110 content coding negotiation: an explicit gzip (or x-gzip) q-value wins over `*`, and q=0 refuses."""
    qualities: dict[str, float] = {}
    for item in accept_encoding.split(","):
        coding, *params = (part.strip() for part in item.split(";"))
        if not coding:
            continue
        quality = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        qualities[coding.lower()] = quality
    for coding in ("gzip", "x-gzip", "*"):
        if coding in qualities:
            return qualities[coding] > 0
    return False


def _index_response(request: HttpRequest, sha256: str, cache_control: str) -> HttpResponse | HttpResponseNotModified:
    """
    The stored gzip body as-is, inflated only for a client that does not accept gzip. A plain Django view: DRF content
    negotiation would refuse an unusual `Accept`. Each representation has its own ETag, so a cache never revalidates
    one encoding's bytes with the other's validator.
    """
    gzipped = _accepts_gzip(request.headers.get("Accept-Encoding", ""))
    etag = f'"{sha256}-gzip"' if gzipped else f'"{sha256}"'
    headers = {"ETag": etag, "Cache-Control": cache_control, "Vary": "Accept-Encoding"}
    if etag in (e.removeprefix("W/") for e in parse_etags(request.headers.get("If-None-Match", ""))):
        return HttpResponseNotModified(headers=headers)
    body = RegionMapFile.objects.filter(pk=sha256).values_list("body", flat=True).first()
    if body is None:
        return JsonResponse({"detail": "No region map file has this sha256."}, status=404)
    if gzipped:
        return HttpResponse(
            bytes(body), content_type="application/json", headers={**headers, "Content-Encoding": "gzip"}
        )
    return HttpResponse(gzip.decompress(body), content_type="application/json", headers=headers)


class RegionMapIndexView(View):
    """The latest region map index, public, revalidated by its checksum. Its `tileset` is the sha256 of the immutable
    vector tileset (`regions/<sha256>.pmtiles`) holding the geometry, published by the pipeline to object storage."""

    def get(self, request: HttpRequest) -> HttpResponse | HttpResponseNotModified:
        # A merge that commits between the snapshot read and the file read deletes the file just resolved: read again.
        for _ in range(2):
            snapshot = RegionMapSnapshot.objects.first()
            if snapshot is None:
                break
            response = _index_response(request, snapshot.checksum, "no-cache")
            if response.status_code != 404:
                return response
        return JsonResponse({"detail": "No region map snapshot has been imported yet."}, status=404)


LEXICON_TTL_SECONDS = 3600


class RegionMapGenresView(View):
    """The genres the latest region map index refers to by Wikidata id, one row per genre, so a client can search
    overviews and regional genres in memory. Public, like the index it complements."""

    def get(self, request: HttpRequest) -> JsonResponse:
        snapshot = RegionMapSnapshot.objects.first()
        if snapshot is None:
            return JsonResponse({"detail": "No region map snapshot has been imported yet."}, status=404)
        # The tree version token is regenerated by DB triggers on every genre or playlist write, so this key can't
        # serve a lexicon from before a rename, move or import.
        key = f"region-map-genres:{snapshot.checksum}:{GenreTreeVersion.current_token()}"
        payload = cache.get(key)
        if payload is None:
            body = RegionMapFile.objects.filter(pk=snapshot.checksum).values_list("body", flat=True).first()
            if body is None:
                return JsonResponse({"detail": "No region map file has this sha256."}, status=404)
            item_ids = genre_item_ids(json.loads(gzip.decompress(bytes(body))))
            payload = serialize_lexicon(Genre.objects.region_lexicon(item_ids))
            cache.set(key, payload, LEXICON_TTL_SECONDS)
        return JsonResponse(payload, safe=False)


class RegionMapAttachableView(View):
    """Every place a curator can attach a tradition to: the drawn regions and the hidden ones the latest index keeps
    out of the map, so `tradition_placement_overrides` can name a subdivision that has no genre yet."""

    def get(self, request: HttpRequest) -> JsonResponse:
        snapshot = RegionMapSnapshot.objects.first()
        if snapshot is None:
            return JsonResponse({"detail": "No region map snapshot has been imported yet."}, status=404)
        key = f"region-map-attachable:{snapshot.checksum}"
        targets = cache.get(key)
        if targets is None:
            body = RegionMapFile.objects.filter(pk=snapshot.checksum).values_list("body", flat=True).first()
            if body is None:
                return JsonResponse({"detail": "No region map file has this sha256."}, status=404)
            index = json.loads(gzip.decompress(bytes(body)))
            targets = [
                {"id": region["id"], "name": region["name"], "kind": region["kind"], "hidden": hidden}
                for hidden, regions in ((False, index["regions"]), (True, index.get("hiddenRegions", [])))
                for region in regions
            ]
            cache.set(key, targets, LEXICON_TTL_SECONDS)
        return JsonResponse(targets, safe=False)
