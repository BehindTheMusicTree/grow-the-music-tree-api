import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from tests.utils.AppApiClient import AppApiClient


@pytest.mark.django_db
def test_canonical_tree_payload_budget():
    # A heavy populated summary must never leak back into the landing-page projection.
    Genre.objects.filter(tree_name="canonical").update(summary="Representative summary. " * 100)
    cache.clear()
    try:
        response = AppApiClient().get(reverse("genre-playlist-tree"), {"tree_name": "canonical"})
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()
        assert len(rows) >= 1700
        print(
            f"canonical-tree payload: {len(rows)} nodes, {len(response.content)} bytes, "
            f"{len(response.content) / len(rows):.1f} bytes/node"
        )
        assert len(response.content) / len(rows) <= 1100
        for row in rows:
            if row["criteria"] is not None:
                assert "summary" not in row["criteria"]
    finally:
        cache.clear()
