import base64
import binascii
from uuid import UUID

from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination
from the_music_tree_api_kit.view.pagination.PaginatedResponseFields import PaginatedResponseFields

NO_TOTAL_PARAM = "with_total"
CURSOR_PARAM = "cursor"
PAGINATION_PARAM = "pagination"
CURSOR_MODE = "cursor"
CURSOR_ORDERING = ("uuid",)


def wants_no_total(request: Request) -> bool:
    return request.query_params.get(NO_TOTAL_PARAM) == "false"


def wants_cursor(request: Request) -> bool:
    params = request.query_params
    mode = params.get(PAGINATION_PARAM)
    if mode is not None and mode != CURSOR_MODE:
        raise ParseError(f"`{PAGINATION_PARAM}` only accepts `{CURSOR_MODE}`.")
    # Released genre panels send withTotal=false and follow the cursor in next.
    return mode == CURSOR_MODE or (
        "genre" in params and wants_no_total(request) and not {"page", "ordering", "from"} & params.keys()
    )


def _encode_cursor(uuid: UUID) -> str:
    return base64.urlsafe_b64encode(str(uuid).encode()).decode()


def _decode_cursor(value: str) -> UUID:
    try:
        return UUID(base64.urlsafe_b64decode(value.encode()).decode())
    except (ValueError, binascii.Error, UnicodeDecodeError) as error:
        raise ParseError("Invalid cursor.") from error


class _NoLastPage:
    @property
    def num_pages(self) -> int:
        raise ParseError("Invalid page.")


class OptionalTotalPagination(AppPagination):
    """`?withTotal=false` (seen as `with_total` after CamelToSnakeMiddleware) skips the COUNT(*): fetches one extra row to know whether a next page exists."""

    def paginate_queryset(self, queryset, request, view=None):
        self._cursor_mode = wants_cursor(request)
        self._no_total = self._cursor_mode or wants_no_total(request)
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
            queryset = queryset.filter(uuid__gt=_decode_cursor(raw_cursor))
        rows = list(queryset[: self._size + 1])
        self._has_next = len(rows) > self._size
        rows = rows[: self._size]
        self._next_cursor = _encode_cursor(rows[-1].uuid) if self._has_next else None
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
        previous_link = replace_query_param(url, self.page_query_param, self._number - 1) if self._number > 1 else None
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

    def get_paginated_response_schema(self, schema):
        nullable_int = {"type": "integer", "nullable": True}
        link = {"type": "string", "format": "uri", "nullable": True}
        return {
            "type": "object",
            "required": [
                PaginatedResponseFields.OVERALL_TOTAL,
                PaginatedResponseFields.NEXT,
                PaginatedResponseFields.PREVIOUS,
                PaginatedResponseFields.RESULTS,
                PaginatedResponseFields.PAGE,
                PaginatedResponseFields.PAGE_SIZE,
                PaginatedResponseFields.TOTAL_PAGES,
            ],
            "properties": {
                PaginatedResponseFields.OVERALL_TOTAL: {
                    **nullable_int,
                    "description": "Null with `with_total=false` and in cursor mode.",
                },
                PaginatedResponseFields.NEXT: link,
                PaginatedResponseFields.PREVIOUS: link,
                PaginatedResponseFields.RESULTS: schema,
                PaginatedResponseFields.PAGE: {**nullable_int, "description": "Null in cursor mode."},
                PaginatedResponseFields.PAGE_SIZE: {"type": "integer"},
                PaginatedResponseFields.TOTAL_PAGES: {
                    **nullable_int,
                    "description": "Null with `with_total=false` and in cursor mode.",
                },
            },
        }

    def get_schema_operation_parameters(self, view):
        return [
            *super().get_schema_operation_parameters(view),
            {
                "name": NO_TOTAL_PARAM,
                "required": False,
                "in": "query",
                "description": (
                    "`false` skips the total count. Genre requests without `page`, `ordering` or `from` "
                    "use the genre cursor for compatibility."
                ),
                "schema": {"type": "boolean"},
            },
            {
                "name": PAGINATION_PARAM,
                "required": False,
                "in": "query",
                "description": (
                    "`cursor` switches to keyset pagination (no total, ordered by `uuid`, requires `genre`; "
                    "rejects `page`, `ordering` and `from`)."
                ),
                "schema": {"type": "string", "enum": [CURSOR_MODE]},
            },
            {
                "name": CURSOR_PARAM,
                "required": False,
                "in": "query",
                "description": "Opaque cursor from the previous page's `next` link, in cursor mode.",
                "schema": {"type": "string"},
            },
        ]
