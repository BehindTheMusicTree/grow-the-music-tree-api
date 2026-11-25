from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination
from the_music_tree_api_kit.view.pagination.PaginatedResponseFields import PaginatedResponseFields

from grow.view.pagination.keyset import SORT_KEY, seek
from grow.view.pagination.song_cursor import PK_ORDERING, SongCursor, cursor_ordering

NO_TOTAL_PARAM = "with_total"
CURSOR_PARAM = "cursor"
PAGINATION_PARAM = "pagination"
CURSOR_MODE = "cursor"


def wants_total(request: Request) -> bool | None:
    value = request.query_params.get(NO_TOTAL_PARAM)
    if value not in (None, "true", "false"):
        raise ParseError(f"`{NO_TOTAL_PARAM}` must be `true` or `false`.")
    return None if value is None else value == "true"


def wants_cursor(request: Request) -> bool:
    """Cursor pagination is the default; `page` selects the numbered pages released clients still use."""
    mode = request.query_params.get(PAGINATION_PARAM)
    if mode is not None and mode != CURSOR_MODE:
        raise ParseError(f"`{PAGINATION_PARAM}` only accepts `{CURSOR_MODE}`.")
    return "page" not in request.query_params


def next_cursor_link(request: Request, cursor: str) -> str:
    url = request.build_absolute_uri()
    if "from" in request.query_params:
        # `from` only positions the first page; the cursor takes over. The total counted the list from that song, so
        # later pages don't recount a different one. The URL keeps the client's spelling of `with_total`.
        for param in ("from", NO_TOTAL_PARAM, "withTotal"):
            url = remove_query_param(url, param)
    return replace_query_param(url, CURSOR_PARAM, cursor)


class _NoLastPage:
    @property
    def num_pages(self) -> int:
        raise ParseError("Invalid page.")


class OptionalTotalPagination(AppPagination):
    """`?withTotal=false` (seen as `with_total` after CamelToSnakeMiddleware) skips the COUNT(*): fetches one extra row to know whether a next page exists."""

    def paginate_queryset(self, queryset, request, view=None):
        self._cursor_mode = wants_cursor(request)
        with_total = wants_total(request)
        self._no_total = self._cursor_mode or with_total is False
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
        """`queryset` must be ordered by `ordering` (SORT_KEY annotated) or, without it, by pk."""
        self._number = None
        ordering = cursor_ordering(request.query_params)  # already validated by the filterset
        keyed = ordering != PK_ORDERING
        self._total = queryset.count() if wants_total(request) else None
        raw_cursor = request.query_params.get(CURSOR_PARAM)
        if raw_cursor:
            cursor = SongCursor.decode(raw_cursor, ordering)
            queryset = seek(
                queryset,
                cursor.key,
                cursor.song_id,
                descending=ordering.startswith("-"),
                inclusive=False,
                keyed=keyed,
            )
        rows = list(queryset[: self._size + 1])
        self._has_next = len(rows) > self._size
        rows = rows[: self._size]
        self._next_cursor = None
        if self._has_next:
            last = rows[-1]
            self._next_cursor = SongCursor(ordering, getattr(last, SORT_KEY) if keyed else None, last.pk).encode()
        return rows

    def get_paginated_response(self, data):
        if not self._no_total:
            return super().get_paginated_response(data)
        if self._cursor_mode:
            next_link = next_cursor_link(self.request, self._next_cursor) if self._has_next else None
            return Response(
                {
                    PaginatedResponseFields.OVERALL_TOTAL: self._total,
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
                    "description": "Null with `with_total=false`, and in cursor mode unless `with_total=true`.",
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
                    "With `page`, `false` skips the total count. Without `page` (cursor mode) the total is only "
                    "counted with `true`."
                ),
                "schema": {"type": "boolean"},
            },
            {
                "name": PAGINATION_PARAM,
                "required": False,
                "in": "query",
                "description": "Deprecated and without effect: requests without `page` use cursor pagination.",
                "deprecated": True,
                "schema": {"type": "string", "enum": [CURSOR_MODE]},
            },
            {
                "name": CURSOR_PARAM,
                "required": False,
                "in": "query",
                "description": (
                    "Opaque cursor from the previous page's `next` link; only valid with the same `ordering`, and "
                    "not with `page` or `from`."
                ),
                "schema": {"type": "string"},
            },
        ]
