from typing import Any

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.curation.lists import CURATION_LISTS
from grow.curation.rows import InvalidRow, ParsedRow, find_exclusivity_conflict, parse_row
from grow.model.curation.CurationEntry import CurationEntry
from grow.view.permission.IsAdmin import IsAdmin
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin


def _entries():
    return CurationEntry.objects.filter(user=None)


def _serialize(entry: CurationEntry) -> dict[str, Any]:
    return {"uuid": entry.uuid, "row": entry.row, "created_on": entry.created_on, "updated_on": entry.updated_on}


def _check_list(list_name: str) -> None:
    if list_name not in CURATION_LISTS:
        raise Http404


def _validate(list_name: str, row: Any, exclude_pk: Any = None) -> ParsedRow:
    if not isinstance(row, dict):
        raise ValidationError({"row": "Must be an object keyed by the list's columns"})
    try:
        parsed = parse_row(list_name, row)
    except InvalidRow as e:
        raise ValidationError({"row": e.errors}) from e
    if _entries().filter(list_name=list_name, key=parsed.key).exclude(pk=exclude_pk).exists():
        raise ValidationError({"row": f"An entry with this key already exists in {list_name}"})
    conflict = find_exclusivity_conflict(_entries(), list_name, parsed.key, exclude_pk)
    if conflict:
        raise ValidationError({"row": f"{parsed.key} is already in {conflict}; these lists are mutually exclusive"})
    return parsed


class CurationView(APIView):
    authentication_classes = [GoogleIdTokenAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAdmin]


class CurationListsView(CurationView):
    def get(self, request: Request) -> Response:
        return Response(
            [
                {"name": name, "key_columns": c.key, "columns": c.columns, "description": c.description}
                for name, c in CURATION_LISTS.items()
            ]
        )


class CurationEntriesView(CurationView):
    def get(self, request: Request, list_name: str) -> Response:
        _check_list(list_name)
        paginator = AppPagination()
        page = paginator.paginate_queryset(_entries().filter(list_name=list_name).order_by("key"), request, view=self)
        return paginator.get_paginated_response([_serialize(e) for e in page or []])

    @transaction.atomic
    def post(self, request: Request, list_name: str) -> Response:
        _check_list(list_name)
        parsed = _validate(list_name, request.data.get("row"))
        entry = CurationEntry.objects.create(
            actor=request.user,
            user=None,
            list_name=list_name,
            key=parsed.key,
            values=parsed.values,
            reason=parsed.reason,
        )
        return Response(_serialize(entry), status=status.HTTP_201_CREATED)


class CurationEntryView(CurationView):
    def _get(self, list_name: str, uuid: str) -> CurationEntry:
        _check_list(list_name)
        return get_object_or_404(_entries(), list_name=list_name, uuid=uuid)

    @transaction.atomic
    def patch(self, request: Request, list_name: str, uuid: str) -> Response:
        entry = self._get(list_name, uuid)
        row = request.data.get("row")
        if not isinstance(row, dict):
            raise ValidationError({"row": "Must be an object keyed by the list's columns"})
        parsed = _validate(list_name, {**entry.row, **row}, exclude_pk=entry.pk)
        entry = CurationEntry.objects.update_instance(
            entry, actor=request.user, key=parsed.key, values=parsed.values, reason=parsed.reason
        )
        return Response(_serialize(entry))

    @transaction.atomic
    def delete(self, request: Request, list_name: str, uuid: str) -> Response:
        CurationEntry.objects.delete_instance(self._get(list_name, uuid), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurationExportView(CurationView):
    """Every list as CSV-ready rows (header order, snake_case, booleans as "true"/""): the pipeline's input."""

    permission_classes = [IsPipelineOrAdmin]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        export: dict[str, list[dict[str, str]]] = {name: [] for name in CURATION_LISTS}
        for entry in _entries().order_by("list_name", "key"):
            export[entry.list_name].append(entry.csv_row)
        return Response(export)
