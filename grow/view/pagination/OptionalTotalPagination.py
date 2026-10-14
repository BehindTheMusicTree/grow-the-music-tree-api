from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param
from the_music_tree_api_kit.view.pagination.AppPagination import AppPagination
from the_music_tree_api_kit.view.pagination.PaginatedResponseFields import PaginatedResponseFields

NO_TOTAL_PARAM = "with_total"


def wants_no_total(request: Request) -> bool:
    return request.query_params.get(NO_TOTAL_PARAM) == "false"


class _NoLastPage:
    @property
    def num_pages(self) -> int:
        raise ParseError("Invalid page.")


class OptionalTotalPagination(AppPagination):
    """`?withTotal=false` (seen as `with_total` after CamelToSnakeMiddleware) skips the COUNT(*): fetches one extra row to know whether a next page exists."""

    def paginate_queryset(self, queryset, request, view=None):
        self._no_total = wants_no_total(request)
        if not self._no_total:
            return super().paginate_queryset(queryset, request, view)
        self.request = request
        self._size = self.get_page_size(request)
        self._number = self.get_page_number(request, _NoLastPage())
        start = (self._number - 1) * self._size
        rows = list(queryset[start : start + self._size + 1])
        self._has_next = len(rows) > self._size
        return rows[: self._size]

    def get_paginated_response(self, data):
        if not self._no_total:
            return super().get_paginated_response(data)
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
