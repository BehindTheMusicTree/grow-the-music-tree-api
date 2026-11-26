import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from tests.utils.AppApiClient import AppApiClient


@pytest.mark.django_db(transaction=True)
def test_artists_name_resolves_artists_through_the_trigram_index():
    """A rare name is only cheap if its artists are found without scanning grow_artist (1.9M rows in prod)."""
    with CaptureQueriesContext(connection) as captured:
        response = AppApiClient().get(reverse("song-list"), {"artists_name": "zzyzx"})
    assert response.status_code == status.HTTP_200_OK
    lookups = [q["sql"] for q in captured.captured_queries if q["sql"].startswith('SELECT "grow_artist"."uuid"')]
    assert len(lookups) == 1, captured.captured_queries
    with transaction.atomic(), connection.cursor() as cursor:
        # The pinned fixture is small enough for a sequential scan to win; forbidding it checks an index can answer.
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(f"EXPLAIN (COSTS OFF) {lookups[0]}")
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "grow_artist_folded_name_trgm" in plan, plan
