import hashlib
import json
from typing import Any

from django.db import transaction
from django.http import HttpResponseNotModified
from django.utils.http import parse_etags
from djangorestframework_camel_case.util import underscoreize
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from grow.model.genealogy.GenealogySnapshot import GenealogySnapshot
from grow.model.import_run.ImportRun import ImportRun
from grow.serializer.model.genealogy.GenealogyDocumentSerializer import GenealogyDocumentSerializer
from grow.view.curation import CurationView
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin


def _checksum(document: dict[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class GenealogyImportView(CurationView):
    """Pipeline import of the genealogy document. Parsed and rendered verbatim: the document's keys must not be recased."""

    permission_classes = [IsPipelineOrAdmin]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def post(self, request: Request) -> Response:
        if not isinstance(request.data, dict):
            raise ValidationError({"non_field_errors": ["Expected a JSON object."]})
        document = request.data
        serializer = GenealogyDocumentSerializer(data=underscoreize(document))
        serializer.is_valid(raise_exception=True)
        checksum = _checksum(document)
        traditions_count = len(document["traditions"])

        with transaction.atomic():
            latest = GenealogySnapshot.objects.first()
            unchanged = latest is not None and latest.checksum == checksum
            run = ImportRun.objects.create(
                kind=ImportRun.Kind.GENEALOGY,
                count=traditions_count,
                skipped_count=traditions_count if unchanged else None,
            )
            if not unchanged:
                GenealogySnapshot.objects.create(document=document, checksum=checksum, import_run=run)

        return Response(
            {"checksum": checksum, "created": not unchanged},
            status=status.HTTP_200_OK if unchanged else status.HTTP_201_CREATED,
        )


class GenealogyView(APIView):
    """The latest genealogy snapshot, public, revalidated by its checksum."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response | HttpResponseNotModified:
        snapshot = GenealogySnapshot.objects.first()
        if snapshot is None:
            raise NotFound("No genealogy snapshot has been imported yet.")
        etag = f'"{snapshot.checksum}"'
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if etag in (e.removeprefix("W/") for e in parse_etags(request.headers.get("If-None-Match", ""))):
            return HttpResponseNotModified(headers=headers)
        return Response(snapshot.document, headers=headers)
