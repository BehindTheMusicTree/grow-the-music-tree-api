import base64
import binascii
from uuid import UUID

from django.db.models import F
from django.db.models.fields.tuple_lookups import TupleGreaterThan
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination
from the_music_tree_api_kit.view.pagination.PaginatedResponseFields import PaginatedResponseFields

NO_TOTAL_PARAM = "with_total"
CURSOR_PARAM = "cursor"
CURSOR_ORDERING = ("genre_id", "uuid")


def wants_no_total(request: Request) -> bool:
    return request.query_params.get(NO_TOTAL_PARAM) == "false"


def wants_cursor(request: Request) -> bool:
    """Keyset mode: no total and no explicit page (a `page` param keeps the OFFSET path for older clients)."""
    return wants_no_total(request) and "page" not in request.query_params


def _encode_cursor(genre_id: UUID, uuid: UUID) -> str:
    return base64.urlsafe_b64encode(f"{genre_id}:{uuid}".encode()).decode()


def _decode_cursor(value: str) -> tuple[UUID, UUID]:
    try:
        genre_id, uuid = base64.urlsafe_b64decode(value.encode()).decode().split(":")
        return UUID(genre_id), UUID(uuid)
    except (ValueError, binascii.Error, UnicodeDecodeError) as error:
        raise ParseError("Invalid cursor.") from error


class _NoLastPage:
    @property
    def num_pages(self) -> int:
        raise ParseError("Invalid page.")


class OptionalTotalPagination(AppPagination):
    """`?withTotal=false` (seen as `with_total` after CamelToSnakeMiddleware) skips the COUNT(*): fetches one extra row to know whether a next page exists."""

    def paginate_queryset(self, queryset, request, view=None):
        self._no_total = wants_no_total(request)
        self._cursor_mode = wants_cursor(request)
        if not self._no_total:
            return super().paginate_queryset(queryset, request, view)
        self.request = request
        self._size = self.get_page_size(request)
        if self._cursor_mode:
            return self._paginate_keyset(queryset, request)
        self._number = self.get_page_number(request, _NoLastPage())
        start = (self._number - 1) * self._size
        rows = list(queryset[start : start + self._size + 1])
        self._has_next = len(rows) > self._size
        return rows[: self._size]

    def _paginate_keyset(self, queryset, request):
        """`queryset` must be ordered by CURSOR_ORDERING: the next page is a single index range scan, whatever the depth."""
        self._number = None
        raw_cursor = request.query_params.get(CURSOR_PARAM)
        if raw_cursor:
            queryset = queryset.filter(
                TupleGreaterThan((F(CURSOR_ORDERING[0]), F(CURSOR_ORDERING[1])), _decode_cursor(raw_cursor))
            )
        rows = list(queryset[: self._size + 1])
        self._has_next = len(rows) > self._size
        rows = rows[: self._size]
        self._next_cursor = _encode_cursor(rows[-1].genre_id, rows[-1].uuid) if self._has_next else None
        return rows

    def get_paginated_response(self, data):
        if not self._no_total:
            return super().get_paginated_response(data)
        if self._cursor_mode:
            next_link = (
                replace_query_param(self.request.build_absolute_uri(), CURSOR_PARAM, self._next_cursor)
                if self._has_next
                else None
            )
            return Response(
                {
                    PaginatedResponseFields.OVERALL_TOTAL: None,
                    PaginatedResponseFields.NEXT: next_link,
                    PaginatedResponseFields.PREVIOUS: None,
                    PaginatedResponseFields.RESULTS: data,
                    PaginatedResponseFields.PAGE: None,
                    PaginatedResponseFields.PAGE_SIZE: self._size,
                    PaginatedResponseFields.TOTAL_PAGES: None,
                }
            )
        url = self.request.build_absolute_uri()
        next_link = replace_query_param(url, self.page_query_param, self._number + 1) if self._has_next else None
        previous_link = None
        if self._number > 1:
            previous_link = (
                remove_query_param(url, self.page_query_param)
                if self._number == 2
                else replace_query_param(url, self.page_query_param, self._number - 1)
            )
        return Response(
            {
                PaginatedResponseFields.OVERALL_TOTAL: None,
                PaginatedResponseFields.NEXT: next_link,
                PaginatedResponseFields.PREVIOUS: previous_link,
                PaginatedResponseFields.RESULTS: data,
                PaginatedResponseFields.PAGE: self._number,
                PaginatedResponseFields.PAGE_SIZE: self._size,
                PaginatedResponseFields.TOTAL_PAGES: None,
            }
        )
