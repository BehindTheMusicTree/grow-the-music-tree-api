from time import perf_counter

import pytest
from django.db import connection

from grow.artist.bulk_import.merge import merge_artist_import_run
from tests.utils.AppTestCase import AppTestCase

SIZE = 4000
GROWTH = 4
# Linear merge time gives a ratio of about GROWTH; the old unhashed NOT IN stale check gave about GROWTH ** 2.
MAX_RATIO = 14

STAGE_RUN = """
INSERT INTO grow_artist_import_staging (run_id, part, musicbrainz_artist_id, data)
SELECT %(run)s, 0, md5('artist' || %(run)s || '/' || i)::uuid, jsonb_build_object(
    'musicbrainz_artist_id', md5('artist' || %(run)s || '/' || i)::uuid, 'name', 'Artist ' || i, 'type', 'group', 'country', 'GB',
    'begin_year', 1990, 'end_year', NULL, 'ended', false,
    'members', (
        SELECT jsonb_agg(jsonb_build_object('musicbrainz_artist_id', md5('artist' || %(run)s || '/' || ((i + k) %% %(count)s))::uuid,
            'begin_year', 1990, 'end_year', NULL, 'ended', false, 'roles', jsonb_build_array('vocals')))
        FROM generate_series(1, 2) k
    ),
    'links', (
        SELECT jsonb_agg(jsonb_build_object('kind', 'official', 'url', 'https://example.com/' || i || '/' || k))
        FROM generate_series(1, 2) k
    ),
    'release_groups', (
        SELECT jsonb_agg(jsonb_build_object('musicbrainz_release_group_id', md5('release' || %(run)s || '/' || i || '/' || k)::uuid,
            'title', 'Release ' || i || '/' || k, 'primary_type', 'Album', 'secondary_types', '[]'::jsonb,
            'first_release_year', 2000))
        FROM generate_series(1, 2) k
    )
)
FROM generate_series(1, %(count)s) i
"""

PRE_EXISTING = """
INSERT INTO grow_artist (uuid, created_on, name, user_id, musicbrainz_artist_id, ended)
SELECT gen_random_uuid(), now(), 'Stale ' || i, NULL, md5('stale' || %(run)s || '/' || i)::uuid, false
FROM generate_series(1, %(count)s) i
"""


@pytest.mark.postgres
class TestArtistMergeScaling(AppTestCase):
    def _timed_merge(self, run_id: int, count: int) -> float:
        with connection.cursor() as cursor:
            cursor.execute(STAGE_RUN, {"run": run_id, "count": count})
            cursor.execute(PRE_EXISTING, {"run": run_id, "count": count // 4})
            cursor.execute("ANALYZE grow_artist_import_staging")
            started = perf_counter()
        merge_artist_import_run(run_id, None, False)
        return perf_counter() - started

    def test_merge_time_grows_linearly_with_run_size(self):
        with connection.cursor() as cursor:
            # A tiny work_mem puts small runs where prod's 4 MB puts a full one: past what a hashed subplan holds.
            cursor.execute("SET LOCAL work_mem = '64kB'")
        self._timed_merge(1, SIZE // 4)  # warm-up
        # Best of two per size, to shrug off a noisy runner.
        small = min(self._timed_merge(2, SIZE), self._timed_merge(3, SIZE))
        large = min(self._timed_merge(4, SIZE * GROWTH), self._timed_merge(5, SIZE * GROWTH))

        assert large / small < MAX_RATIO, f"{SIZE} artists: {small:.2f}s, {SIZE * GROWTH}: {large:.2f}s"
