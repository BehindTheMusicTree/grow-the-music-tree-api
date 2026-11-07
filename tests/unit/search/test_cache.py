from django.core.cache import cache
from django.test import SimpleTestCase

from grow.search.cache import SearchCache, cached_search, invalidate_search_cache


class TestCachedSearch(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_hit_skips_compute(self):
        assert cached_search(SearchCache.SONGS, "Numb", (10,), lambda: [{"title": "Numb"}]) == [{"title": "Numb"}]
        assert cached_search(SearchCache.SONGS, " numb ", (10,), list) == [{"title": "Numb"}]
        assert cached_search(SearchCache.SONGS, "numb", (5,), list) == []

    def test_invalidation_only_hits_its_namespace(self):
        cached_search(SearchCache.SONGS, "numb", (10,), lambda: [{"title": "Numb"}])
        cached_search(SearchCache.ARTISTS, "numb", (10,), lambda: [{"name": "Numb"}])

        invalidate_search_cache(SearchCache.SONGS)

        assert cached_search(SearchCache.SONGS, "numb", (10,), list) == []
        assert cached_search(SearchCache.ARTISTS, "numb", (10,), list) == [{"name": "Numb"}]

    def test_results_computed_across_an_invalidation_are_never_served(self):
        def stale():
            invalidate_search_cache(SearchCache.SONGS)
            return [{"title": "Old"}]

        assert cached_search(SearchCache.SONGS, "numb", (10,), stale) == [{"title": "Old"}]
        assert cached_search(SearchCache.SONGS, "numb", (10,), lambda: [{"title": "New"}]) == [{"title": "New"}]
