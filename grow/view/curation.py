import re
import uuid
from datetime import UTC
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q, TextField
from django.db.models.functions import Cast, Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination

from grow.authentication.ApiKeyAuthentication import ApiKeyAuthentication
from grow.authentication.GoogleIdTokenAuthentication import GoogleIdTokenAuthentication
from grow.curation.edges import (
    RELATION_BY_LIST,
    edge_csv_row,
    edge_rules,
    find_edge_rules,
    legacy_key,
    legacy_list_name,
    project_legacy_lists,
)
from grow.curation.labels import item_ids, resolve_item_labels, snapshot_item_ids
from grow.curation.lists import (
    ADDITION_LISTS,
    CURATION_LISTS,
    EDGE_PROJECTION_LISTS,
    ITEM_ID_COLUMNS,
    ITEM_ID_PATTERN,
    KEY_MAX_LENGTH,
)
from grow.curation.resolutions import apply_wikidata_resolutions
from grow.curation.rows import InvalidRow, ParsedRow, RowConflict, check_edit, find_item_rules, lock_writes
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from grow.model.curation.WikidataItem import WikidataItem
from grow.model.history.HistoryEntry import HistoryEntry
from grow.serializer.model.history.output.curation import CurationHistoryEntrySerializer
from grow.view.permission.IsAdmin import IsAdmin
from grow.view.permission.IsCuratorOrAdmin import IsCuratorOrAdmin
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
        return check_edit(_entries(), list_name, row, exclude_pk)
    except InvalidRow as e:
        raise ValidationError({"row": e.errors}) from e
    except RowConflict as e:
        raise ValidationError({"row": str(e)}) from e


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
    """Name of every item id on the page, keyed by id."""
    return resolve_item_labels(item_ids(e.row for e in entries))


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
                    "column_specs": c.column_specs,
                    "description": c.description,
                    "count": counts.get(name, 0),
                }
                for name, c in CURATION_LISTS.items()
            ]
        )


class CurationEntriesView(CurationView):
    permission_classes = [IsCuratorOrAdmin]

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
    permission_classes = [IsCuratorOrAdmin]

    def _get(self, list_name: str, uuid: str) -> CurationEntry:
        _check_list(list_name)
        lock_writes(_entries())
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


def _item_id_field(**kwargs) -> serializers.RegexField:
    return serializers.RegexField(rf"^(?:{ITEM_ID_PATTERN})$", **kwargs)


class _StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict) and (unknown := set(data) - set(self.fields)):
            raise ValidationError(dict.fromkeys(sorted(unknown), "Unknown field"))
        return super().to_internal_value(data)


def _serialize_edge(rule: GenreEdgeRule) -> dict[str, Any]:
    return {"uuid": rule.uuid, "row": rule.row, "created_on": rule.created_on, "updated_on": rule.updated_on}


def _edge_labels(rules: list[GenreEdgeRule]) -> dict[str, str]:
    return resolve_item_labels(item_ids(r.row for r in rules))


def _edge_errors(e: DjangoValidationError | InvalidRow) -> dict[str, Any]:
    if isinstance(e, InvalidRow):
        return e.errors
    if hasattr(e, "error_dict"):
        return {("edge" if field == "__all__" else field): messages for field, messages in e.message_dict.items()}
    return {"edge": e.messages}


class _EdgeSerializer(_StrictSerializer):
    relation = serializers.ChoiceField(choices=GenreEdgeRule.Relation.choices)
    item_id = _item_id_field()
    parent_item_id = _item_id_field(required=False, allow_null=True, default=None)
    action = serializers.ChoiceField(
        choices=GenreEdgeRule.Action.choices, required=False, allow_null=True, default=None
    )
    exclude_other_parents = serializers.BooleanField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(required=False, allow_blank=True, default="", trim_whitespace=False)


class _EdgePatchSerializer(_StrictSerializer):
    parent_item_id = _item_id_field(required=False, allow_null=True)
    action = serializers.ChoiceField(choices=GenreEdgeRule.Action.choices, required=False, allow_null=True)
    exclude_other_parents = serializers.BooleanField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)


class CurationEdgesView(CurationView):
    """The curated genre edges (canonical/regional parents, roots, regional overviews, secondary parents)."""

    permission_classes = [IsCuratorOrAdmin]

    def get(self, request: Request) -> Response:
        queryset = edge_rules()
        if "item_id" in request.query_params:
            queryset = find_edge_rules(_item_id(request))
        relation = request.query_params.get("relation")
        if relation:
            if relation not in GenreEdgeRule.Relation.values:
                raise ValidationError({"relation": f"Must be one of {', '.join(GenreEdgeRule.Relation.values)}"})
            queryset = queryset.filter(relation=relation)
        q = request.query_params.get("q", "").strip()
        if q:
            qids = _canonical_genres().filter(_name__icontains=q).exclude(wikidata_id=None).values("wikidata_id")
            queryset = queryset.filter(
                Q(item_id__icontains=q)
                | Q(parent_item_id__icontains=q)
                | Q(reason__icontains=q)
                | Q(item_id__in=qids)
                | Q(parent_item_id__in=qids)
            )
        paginator = AppPagination()
        page = paginator.paginate_queryset(
            queryset.order_by("item_id", "relation", "parent_item_id"), request, view=self
        )
        rules = list(page or [])
        response = paginator.get_paginated_response([_serialize_edge(r) for r in rules])
        response.data["labels"] = _edge_labels(rules)
        return response

    @transaction.atomic
    def post(self, request: Request) -> Response:
        serializer = _EdgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rule = GenreEdgeRule.objects.create(actor=request.user, user=None, **serializer.validated_data)
        except (DjangoValidationError, InvalidRow) as e:
            raise ValidationError(_edge_errors(e)) from e
        return Response(_serialize_edge(rule), status=status.HTTP_201_CREATED)


class CurationEdgeView(CurationView):
    permission_classes = [IsCuratorOrAdmin]

    def _get(self, uuid: str) -> GenreEdgeRule:
        lock_writes(edge_rules())
        return get_object_or_404(edge_rules(), uuid=uuid)

    @transaction.atomic
    def patch(self, request: Request, uuid: str) -> Response:
        rule = self._get(uuid)
        serializer = _EdgePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rule = GenreEdgeRule.objects.update_instance(rule, actor=request.user, **serializer.validated_data)
        except (DjangoValidationError, InvalidRow) as e:
            raise ValidationError(_edge_errors(e)) from e
        return Response(_serialize_edge(rule))

    @transaction.atomic
    def delete(self, request: Request, uuid: str) -> Response:
        GenreEdgeRule.objects.delete_instance(self._get(uuid), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurationRulesView(CurationView):
    """Every canonical entry and edge referencing an item."""

    def get(self, request: Request) -> Response:
        item_id = _item_id(request)
        entries = list(find_item_rules(_entries(), item_id).order_by("list_name", "key"))
        edges = list(find_edge_rules(item_id).order_by("item_id", "relation", "parent_item_id"))
        return Response(
            {
                "results": [{"list_name": e.list_name, **_serialize(e)} for e in entries],
                "edges": [_serialize_edge(r) for r in edges],
                "labels": {**_labels(entries), **_edge_labels(edges)},
            }
        )


class CurationHistoryView(CurationView):
    """Edits to canonical entries and edges, newest first, optionally narrowed to a `list`, an `entry` uuid or an `item_id`."""

    def get(self, request: Request) -> Response:
        params = request.query_params
        content_types = ContentType.objects.get_for_models(CurationEntry, GenreEdgeRule).values()
        queryset = HistoryEntry.objects.filter(user=None, content_type__in=content_types)
        if "list" in params:
            if params["list"] not in (*CURATION_LISTS, *EDGE_PROJECTION_LISTS):
                raise ValidationError({"list": "Unknown curation list"})
            # Edits made before migration 0112 stay under the entry content type with a `list_name`; later ones are
            # edge snapshots carrying a `relation`.
            matching = _snapshot_has("list_name", params["list"])
            if params["list"] in RELATION_BY_LIST:
                matching |= Q(content_type=ContentType.objects.get_for_model(GenreEdgeRule)) & _snapshot_has(
                    "relation", RELATION_BY_LIST[params["list"]]
                )
            queryset = queryset.filter(matching)
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
        response = paginator.get_paginated_response(CurationHistoryEntrySerializer(page, many=True).data)
        snapshots = [v for h in page or [] for v in (h.old_value, h.new_value)]
        response.data["labels"] = resolve_item_labels(snapshot_item_ids(snapshots))
        return response


class CurationStatusView(CurationView):
    """Which pipeline export the canonical tree was last built from, and how many entries were edited since."""

    def get(self, request: Request) -> Response:
        state = CurationSyncState.load()
        return Response({"applied_export_on": state.applied_export_on, "pending_count": state.pending_count})


class CurationExportView(CurationView):
    """Every list, and the edges, as CSV-ready rows (header order, snake_case, booleans as "true"/""): the pipeline's input.

    `exported_on` is the export's instant: the pipeline carries it into Gold and sends it back on tree import, so grow
    knows which export the imported tree was built from.
    """

    permission_classes = [IsPipelineOrAdmin]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        exported_on = timezone.now()
        if request.auth.role == "pipeline":
            CurationSyncState.objects.update_or_create(pk=1, defaults={"exported_on": exported_on})
        export: dict[str, Any] = {name: [] for name in CURATION_LISTS}
        for entry in _entries().order_by("list_name", "key"):
            export[entry.list_name].append(entry.csv_row)
        export.update(project_legacy_lists())
        export["edges"] = [
            edge_csv_row(r) for r in sorted(edge_rules(), key=lambda r: (r.item_id, r.relation, r.parent_item_id or ""))
        ]
        export["exported_on"] = exported_on.isoformat()
        return Response(export)


class _CurationItemSerializer(serializers.Serializer):
    """An item id of a curation entry (`list` + `key`) or of an edge rule (`rule_id`, or the legacy `list` + `key`)."""

    rule_id = serializers.UUIDField(required=False)
    list = serializers.ChoiceField(choices=[*CURATION_LISTS, *EDGE_PROJECTION_LISTS], required=False)
    key = serializers.CharField(max_length=KEY_MAX_LENGTH, trim_whitespace=False, required=False)
    column = serializers.ChoiceField(choices=sorted(ITEM_ID_COLUMNS))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "rule_id" in attrs:
            if "list" in attrs or "key" in attrs:
                raise ValidationError({"rule_id": "Can't be combined with list and key"})
            if attrs["column"] not in ("item_id", "parent_item_id"):
                raise ValidationError({"column": "Must be item_id or parent_item_id for a rule_id"})
            return attrs
        if "list" not in attrs or "key" not in attrs:
            raise ValidationError({"rule_id": "Required unless list and key are given"})
        columns = {**CURATION_LISTS, **EDGE_PROJECTION_LISTS}[attrs["list"]].columns
        if attrs["column"] not in columns:
            raise ValidationError({"column": f"Not a column of {attrs['list']}"})
        return attrs


class _RemapSerializer(_CurationItemSerializer):
    to = _item_id_field()

    def get_fields(self) -> dict[str, serializers.Field]:
        return {**super().get_fields(), "from": _item_id_field()}  # `from` is a Python keyword


class _ItemRefSerializer(_StrictSerializer):
    id = _item_id_field()
    label = serializers.CharField(allow_null=True, allow_blank=True, trim_whitespace=False)


class _EvidenceSerializer(_StrictSerializer):
    label = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    modified = serializers.DateTimeField(required=False, default_timezone=UTC)
    instance_of = _ItemRefSerializer(many=True, required=False)
    subclass_of = _ItemRefSerializer(many=True, required=False)
    has_indigenous_to = serializers.BooleanField(required=False)
    conflict_list = serializers.ChoiceField(choices=[*CURATION_LISTS, *EDGE_PROJECTION_LISTS], required=False)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        value = super().to_internal_value(data)
        if "modified" in value:
            value["modified"] = value["modified"].isoformat()
        return value


class _ReviewItemSerializer(_CurationItemSerializer):
    item_id = _item_id_field()
    reason = serializers.ChoiceField(choices=CurationReviewItem.Reason.choices)
    target = _item_id_field(required=False, allow_null=True)
    evidence = _EvidenceSerializer(required=False, allow_null=True)


class _WikidataResolutionsSerializer(serializers.Serializer):
    remaps = _RemapSerializer(many=True)
    review = _ReviewItemSerializer(many=True)


class CurationWikidataResolutionsView(CurationView):
    """The pipeline's Wikidata resolution of curation item ids: redirects to remap, and ids it couldn't resolve."""

    permission_classes = [IsPipelineOrAdmin]

    def post(self, request: Request) -> Response:
        serializer = _WikidataResolutionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(apply_wikidata_resolutions(**serializer.validated_data))


class _WikidataItemSerializer(_StrictSerializer):
    id = _item_id_field()
    label = serializers.CharField(trim_whitespace=False)


class _WikidataItemsSerializer(serializers.Serializer):
    items = _WikidataItemSerializer(many=True)


class CurationWikidataItemsView(CurationView):
    """The pipeline's catalog of every Wikidata item it knows, pruned ones included: replaces the previous one."""

    permission_classes = [IsPipelineOrAdmin]

    @transaction.atomic
    def post(self, request: Request) -> Response:
        serializer = _WikidataItemsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = {i["id"]: i["label"] for i in serializer.validated_data["items"]}
        WikidataItem.objects.all().delete()
        WikidataItem.objects.bulk_create(WikidataItem(item_id=k, label=v) for k, v in items.items())
        return Response({"itemCount": len(items)})


ITEM_SEARCH_LIMIT = 20


class CurationItemsView(CurationView):
    """Items matching `q` by id or name, for an admin to pick one: the canonical tree, the catalog and pending additions."""

    def get(self, request: Request) -> Response:
        q = request.query_params.get("q", "").strip()
        if not q:
            raise ValidationError({"q": "Required"})
        ids = set(
            WikidataItem.objects.filter(Q(item_id__iexact=q) | Q(label__icontains=q)).values_list("item_id", flat=True)[
                :ITEM_SEARCH_LIMIT
            ]
        )
        ids |= set(
            _canonical_genres()
            .filter(Q(_name__icontains=q) | Q(wikidata_id__iexact=q))
            .exclude(wikidata_id=None)
            .values_list("wikidata_id", flat=True)[:ITEM_SEARCH_LIMIT]
        )
        ids |= set(
            _entries()
            .filter(list_name__in=ADDITION_LISTS)
            .annotate(values_text=Cast("values", TextField()))
            .filter(Q(key__iexact=q) | Q(values_text__icontains=q))
            .values_list("key", flat=True)[:ITEM_SEARCH_LIMIT]
        )
        labels = resolve_item_labels(ids)
        results = [
            {"id": i, "label": labels[i]}
            for i in sorted(ids, key=lambda i: (labels.get(i, "~").lower(), i))
            if i in labels
        ]
        return Response({"results": results[:ITEM_SEARCH_LIMIT]})


class CurationReviewView(CurationView):
    """The curation item ids the pipeline's last report couldn't resolve, for an admin to fix."""

    def get(self, request: Request) -> Response:
        items = sorted(
            CurationReviewItem.objects.select_related("rule"),
            key=lambda i: (
                i.list_name or legacy_list_name(i.rule),
                i.key or legacy_key(i.rule),
                i.column,
            ),
        )
        return Response(
            [
                {
                    "rule_id": i.rule.uuid if i.rule else None,
                    "list": i.list_name or legacy_list_name(i.rule),
                    "key": i.key or legacy_key(i.rule),
                    "column": i.column,
                    "item_id": i.item_id,
                    "reason": i.reason,
                    "target": i.target_item_id,
                    "evidence": i.evidence,
                    "reported_on": i.reported_on,
                }
                for i in items
            ]
        )
