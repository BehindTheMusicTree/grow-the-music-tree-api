from urllib.parse import parse_qs, urlsplit

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from grow.view.pagination.OptionalTotalPagination import next_cursor_link


def test_from_and_total_are_dropped_in_any_spelling():
    # As CamelToSnakeMiddleware leaves it: `request.GET` normalized, the URL untouched.
    request = APIRequestFactory().get("/songs/?artist=a&From=x&WithTotal=true&withTotal=true&pageSize=1")
    request.GET = request.GET.copy()
    request.GET["from"] = "x"

    link = next_cursor_link(Request(request), "c")

    assert parse_qs(urlsplit(link).query) == {"artist": ["a"], "pageSize": ["1"], "cursor": ["c"]}
