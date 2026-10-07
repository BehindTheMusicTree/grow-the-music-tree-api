import re
import uuid
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Q, TextField
from django.db.models.functions import Cast, Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.curation.lists import CURATION_LISTS, ITEM_ID_COLUMNS, ITEM_ID_PATTERN
from grow.curation.rows import (
    InvalidRow,
    ParsedRow,
    find_exclusivity_conflict,
    find_item_rules,
    find_precedence_cycle,
    parse_row,
    precedence_cycle_error,
)
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.history.HistoryEntry import HistoryEntry
from grow.serializer.model.history.output.curation import CurationHistoryEntrySerializer
from grow.view.permission.IsAdmin import IsAdmin
from grow.view.permission.IsPipelineOrAdmin import IsPipelineOrAdmin


def _entries():
    return CurationEntry.objects.filter(user=None)


def _serialize(entry: CurationEntry) -> dict[str, Any]:
    return {"uuid": entry.uuid, "row": entry.row, "created_on": entry.created_on, "updated_on": entry.updated_on}


def _check_list(list_name: str) -> None:
    if list_name not in CURATION_LISTS:
        raise Http404


def _row(request: Request) -> dict[str, Any]:
    row = request.data.get("row") if isinstance(request.data, dict) else None
    if not isinstance(row, dict):
        raise ValidationError({"row": "Must be an object keyed by the list's columns"})
    return row


def _validate(list_name: str, row: dict[str, Any], exclude_pk: Any = None) -> ParsedRow:
    try:
        parsed = parse_row(list_name, row)
    except InvalidRow as e:
        raise ValidationError({"row": e.errors}) from e
    if _entries().filter(list_name=list_name, key=parsed.key).exclude(pk=exclude_pk).exists():
        raise ValidationError({"row": f"An entry with this key already exists in {list_name}"})
    conflict = find_exclusivity_conflict(_entries(), list_name, parsed.key, exclude_pk)
    if conflict:
        raise ValidationError({"row": f"{parsed.key} is already in {conflict}; these lists are mutually exclusive"})
    cycle = find_precedence_cycle(_entries(), list_name, parsed.key, exclude_pk)
    if cycle:
        raise ValidationError({"row": precedence_cycle_error(cycle)})
    return parsed


ORDERINGS = {"key": "key", "-updated_on": "-last_edited_on"}


def _canonical_genres():
    return Genre.objects.filter(user=None)


def _search(queryset, q: str):
    """Matches `q` against the key, values, reason, or the name of a genre whose QID is the key."""
    qids = _canonical_genres().filter(_name__icontains=q).exclude(wikidata_id=None).values("wikidata_id")
    return queryset.annotate(values_text=Cast("values", TextField())).filter(
        Q(key__icontains=q) | Q(values_text__icontains=q) | Q(reason__icontains=q) | Q(key__in=qids)
    )


def _labels(entries: list[CurationEntry]) -> dict[str, str]:
    """Canonical genre name of every item id on the page, keyed by QID."""
    ids = {str(v) for e in entries for c, v in e.row.items() if c in ITEM_ID_COLUMNS and v}
    return dict(_canonical_genres().filter(wikidata_id__in=ids).values_list("wikidata_id", "_name"))


def _item_id(request: Request) -> str:
    item_id = request.query_params.get("item_id", "")
    if not re.fullmatch(ITEM_ID_PATTERN, item_id):
        raise ValidationError({"item_id": "Must be a Wikidata QID or a LOCAL:<slug> id"})
    return item_id


def _snapshot_has(column: str, value: str) -> Q:
    fragment = CurationEntry.objects.snapshot_fragment(column, value)
    return Q(old_value__contains=fragment) | Q(new_value__contains=fragment)


class CurationView(APIView):
    authentication_classes = [GoogleIdTokenAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAdmin]


class CurationListsView(CurationView):
    def get(self, request: Request) -> Response:
        counts = dict(_entries().values("list_name").annotate(count=Count("pk")).values_list("list_name", "count"))
        return Response(
            [
                {
                    "name": name,
                    "key_columns": c.key,
                    "columns": c.columns,
                    "description": c.description,
                    "count": counts.get(name, 0),
                }
                for name, c in CURATION_LISTS.items()
            ]
        )


class CurationEntriesView(CurationView):
    def get(self, request: Request, list_name: str) -> Response:
        _check_list(list_name)
        ordering = request.query_params.get("ordering", "key")
        if ordering not in ORDERINGS:
            raise ValidationError({"ordering": f"Must be one of {', '.join(ORDERINGS)}"})
        # `updated_on` stays null until an entry's first edit.
        queryset = _entries().filter(list_name=list_name).annotate(last_edited_on=Coalesce("updated_on", "created_on"))
        q = request.query_params.get("q", "").strip()
        if q:
            queryset = _search(queryset, q)
        paginator = AppPagination()
        page = paginator.paginate_queryset(queryset.order_by(ORDERINGS[ordering], "key"), request, view=self)
        entries = list(page or [])
        response = paginator.get_paginated_response([_serialize(e) for e in entries])
        response.data["labels"] = _labels(entries)
        return response

    @transaction.atomic
    def post(self, request: Request, list_name: str) -> Response:
        _check_list(list_name)
        parsed = _validate(list_name, _row(request))
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
        parsed = _validate(list_name, {**entry.row, **_row(request)}, exclude_pk=entry.pk)
        entry = CurationEntry.objects.update_instance(
            entry, actor=request.user, key=parsed.key, values=parsed.values, reason=parsed.reason
        )
        return Response(_serialize(entry))

    @transaction.atomic
    def delete(self, request: Request, list_name: str, uuid: str) -> Response:
        CurationEntry.objects.delete_instance(self._get(list_name, uuid), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurationRulesView(CurationView):
    """Every canonical entry referencing an item, across lists."""

    def get(self, request: Request) -> Response:
        entries = list(find_item_rules(_entries(), _item_id(request)).order_by("list_name", "key"))
        return Response(
            {
                "results": [{"list_name": e.list_name, **_serialize(e)} for e in entries],
                "labels": _labels(entries),
            }
        )


class CurationHistoryView(CurationView):
    """Edits to canonical entries, newest first, optionally narrowed to a `list`, an `entry` uuid or an `item_id`."""

    def get(self, request: Request) -> Response:
        params = request.query_params
        queryset = HistoryEntry.objects.filter(user=None, content_type=ContentType.objects.get_for_model(CurationEntry))
        if "list" in params:
            if params["list"] not in CURATION_LISTS:
                raise ValidationError({"list": "Unknown curation list"})
            queryset = queryset.filter(_snapshot_has("list_name", params["list"]))
        if "entry" in params:
            try:
                queryset = queryset.filter(content_uuid=uuid.UUID(params["entry"]))
            except ValueError as e:
                raise ValidationError({"entry": "Must be a uuid"}) from e
        if "item_id" in params:
            item_id = _item_id(request)
            query = Q()
            for column in ITEM_ID_COLUMNS:
                query |= _snapshot_has(column, item_id)
            queryset = queryset.filter(query)
        paginator = AppPagination()
        page = paginator.paginate_queryset(
            queryset.select_related("actor__profile").order_by("-created_on"), request, view=self
        )
        return paginator.get_paginated_response(CurationHistoryEntrySerializer(page, many=True).data)


class CurationStatusView(CurationView):
    """Which pipeline export the canonical tree was last built from, and how many entries were edited since."""

    def get(self, request: Request) -> Response:
        applied_export_on = CurationSyncState.load().applied_export_on
        history = HistoryEntry.objects.filter(user=None, content_type=ContentType.objects.get_for_model(CurationEntry))
        if applied_export_on is not None:
            history = history.filter(created_on__gt=applied_export_on)
        pending_count = history.values("content_uuid").distinct().count()
        return Response({"applied_export_on": applied_export_on, "pending_count": pending_count})


class CurationExportView(CurationView):
    """Every list as CSV-ready rows (header order, snake_case, booleans as "true"/""): the pipeline's input."""

    permission_classes = [IsPipelineOrAdmin]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        if request.auth.role == "pipeline":
            CurationSyncState.objects.update_or_create(pk=1, defaults={"exported_on": timezone.now()})
        export: dict[str, list[dict[str, str]]] = {name: [] for name in CURATION_LISTS}
        for entry in _entries().order_by("list_name", "key"):
            export[entry.list_name].append(entry.csv_row)
        return Response(export)
