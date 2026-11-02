from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle

from tests.utils.AppApiClient import AppApiClient
from tests.utils.AppTestCase import AppTestCase

MAX_OFFSET_PATH = "grow.view.pagination.OptionalTotalPagination.MAX_PUBLIC_OFFSET"


class TestCase(AppTestCase):
    """Bounds on what a non-admin can make `GET library/songs/` cost."""

    list_endpoint = "song-list"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.genre = self.model_fixture_factory.create_genre("Rock")
        self.artist = self.model_fixture_factory.create_artist("Pink Floyd")
        for index in range(5):
            self.model_fixture_factory.create_song(title=f"T{index}", genre=self.genre, artists=[self.artist])

    def _public_get(self, data=None, **extra):
        self.api_client.credentials()
        return self.api_client.get(path=reverse(self.list_endpoint), data=data, **extra)

    def _assert_rejected_without_query(self, data):
        with CaptureQueriesContext(connection) as queries:
            response = self._public_get(data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert len(queries) == 0

    def test_public_list_without_scope_is_rejected_before_any_query(self):
        self._assert_rejected_without_query(None)

    def test_public_list_with_text_filter_only_is_rejected_before_any_query(self):
        self._assert_rejected_without_query({"title": "T"})

    def test_admin_list_without_scope_is_allowed(self):
        response = self.api_client.get(path=reverse(self.list_endpoint))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["overallTotal"] == 5

    def test_public_genre_only_in_total_mode_is_rejected_before_any_query(self):
        self._assert_rejected_without_query({"genre": str(self.genre.uuid)})

    def test_public_genre_only_with_page_is_rejected_before_any_query(self):
        self._assert_rejected_without_query({"genre": str(self.genre.uuid), "withTotal": "false", "page": 2})

    def test_public_genre_only_in_cursor_mode_is_allowed(self):
        response = self._public_get({"genre": str(self.genre.uuid), "withTotal": "false"})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert len(response.data["results"]) == 5

    def test_public_genre_and_artist_in_total_mode_is_allowed(self):
        response = self._public_get({"genre": str(self.genre.uuid), "artist": str(self.artist.uuid)})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["overallTotal"] == 5

    def test_public_artist_page_past_the_cap_is_rejected_before_any_query(self):
        with patch(MAX_OFFSET_PATH, 4):
            # page_size 2: page 3 skips 4 rows (allowed), page 4 skips 6 (too deep).
            self._assert_rejected_without_query({"artist": str(self.artist.uuid), "pageSize": 2, "page": 4})

    def test_public_artist_page_at_the_cap_is_allowed(self):
        with patch(MAX_OFFSET_PATH, 4):
            response = self._public_get({"artist": str(self.artist.uuid), "pageSize": 2, "page": 3})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert len(response.data["results"]) == 1

    def test_public_non_numeric_page_is_rejected_before_any_query(self):
        self._assert_rejected_without_query({"artist": str(self.artist.uuid), "page": "last"})

    def test_public_artist_page_past_the_cap_without_total_is_rejected(self):
        with patch(MAX_OFFSET_PATH, 4):
            self._assert_rejected_without_query(
                {"artist": str(self.artist.uuid), "pageSize": 2, "page": 4, "withTotal": "false"}
            )

    def test_public_total_pages_is_clamped_to_reachable_pages_but_overall_total_is_exact(self):
        with patch(MAX_OFFSET_PATH, 2):
            response = self._public_get({"artist": str(self.artist.uuid), "pageSize": 1})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["overallTotal"] == 5
        assert response.data["totalPages"] == 3  # 2 // 1 + 1

    def test_admin_total_pages_and_depth_are_not_capped(self):
        with patch(MAX_OFFSET_PATH, 2):
            response = self.api_client.get(
                path=reverse(self.list_endpoint), data={"artist": str(self.artist.uuid), "pageSize": 1, "page": 5}
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["totalPages"] == 5

    def test_public_from_anchor_is_not_limited_by_the_depth_cap(self):
        anchor = self.model_fixture_factory.create_song(title="T9", genre=self.genre, artists=[self.artist])
        with patch(MAX_OFFSET_PATH, 1):
            response = self._public_get(
                {"artist": str(self.artist.uuid), "from": str(anchor.uuid), "ordering": "title"}
            )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_public_list_is_throttled_but_admin_is_not(self):
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"songs-list": "2/min"}):
            data = {"artist": str(self.artist.uuid)}
            statuses = [self._public_get(data).status_code for _ in range(3)]
            admin_statuses = []
            admin_client = AppApiClient()
            for _ in range(3):
                admin_statuses.append(admin_client.get(path=reverse(self.list_endpoint), data=data).status_code)

        assert statuses == [status.HTTP_200_OK, status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS]
        assert admin_statuses == [status.HTTP_200_OK] * 3

    def test_throttle_ignores_spoofed_leading_forwarded_for_hops(self):
        # NUM_PROXIES=1 in tests: only the hop the trusted proxy appended identifies the client.
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"songs-list": "1/min"}):
            data = {"artist": str(self.artist.uuid)}
            first = self._public_get(data, HTTP_X_FORWARDED_FOR="1.1.1.1, 9.9.9.9")
            second = self._public_get(data, HTTP_X_FORWARDED_FOR="2.2.2.2, 9.9.9.9")
            other_client = self._public_get(data, HTTP_X_FORWARDED_FOR="2.2.2.2, 8.8.8.8")

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert other_client.status_code == status.HTTP_200_OK

    def test_artist_search_is_throttled(self):
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"artist-search": "1/min"}):
            self.api_client.credentials()
            first = self.api_client.get(path=reverse("artist-search"), data={"q": "pink"})
            second = self.api_client.get(path=reverse("artist-search"), data={"q": "pink"})

        # The search itself is Postgres-only; the throttle runs before it, so the first call's own outcome is irrelevant.
        assert first.status_code != status.HTTP_429_TOO_MANY_REQUESTS
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
