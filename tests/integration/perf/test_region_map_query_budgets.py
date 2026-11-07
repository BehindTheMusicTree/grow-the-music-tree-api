import gzip
import hashlib
import json

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from tests.utils.AppApiClient import AppApiClient
from tests.utils.ModelFixtureFactory import ModelFixtureFactory


@pytest.fixture
def region_snapshot():
    factory = ModelFixtureFactory(default_user=None)
    regions = []
    for index in range(12):
        item_id = f"Q{index + 1}"
        factory.create_genre(f"Region genre {index}", wikidata_id=item_id)
        regions.append({"itemId": f"Q{index + 100}", "genres": [{"itemId": item_id}]})
    body = json.dumps({"regions": regions, "tileset": "a" * 64}, sort_keys=True).encode()
    checksum = hashlib.sha256(body).hexdigest()
    compressed = gzip.compress(body, mtime=0)
    RegionMapFile.objects.create(sha256=checksum, body=compressed, size=len(compressed))
    RegionMapSnapshot.objects.create(checksum=checksum)
    cache.clear()


@pytest.mark.django_db
@pytest.mark.parametrize("encoding", ["identity", "gzip"])
@pytest.mark.parametrize("mode", ["cold", "warm", "not-modified"])
def test_region_index_exact_query_budget(region_snapshot, encoding, mode):
    client = AppApiClient()
    path = reverse("region-map-index")
    headers = {"HTTP_ACCEPT_ENCODING": encoding}
    initial = client.get(path, **headers)
    if mode == "cold":
        cache.clear()
    if mode == "not-modified":
        headers["HTTP_IF_NONE_MATCH"] = initial["ETag"]
    with CaptureQueriesContext(connection) as queries:
        response = client.get(path, **headers)
    assert response.status_code == (304 if mode == "not-modified" else 200)
    assert len(queries) == (1 if mode == "not-modified" else 2)


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["cold", "warm", "not-modified"])
def test_region_lexicon_exact_query_budget(region_snapshot, mode):
    client = AppApiClient()
    path = reverse("region-map-genres")
    initial = client.get(path)
    assert len(initial.json()) == 12
    if mode == "cold":
        cache.clear()
    headers = {"HTTP_IF_NONE_MATCH": initial["ETag"]} if mode == "not-modified" else {}
    with CaptureQueriesContext(connection) as queries:
        response = client.get(path, **headers)
    assert response.status_code == (304 if mode == "not-modified" else 200)
    assert len(queries) == (4 if mode == "cold" else 2)
