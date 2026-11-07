import gzip
from unittest.mock import patch

import pytest
from django.urls import reverse

from grow.model.region_map.RegionMapFile import RegionMapFile
from grow.model.region_map.RegionMapSnapshot import RegionMapSnapshot
from perf.region_fixture import CHECKSUM, seed_region_snapshot
from tests.utils.AppApiClient import AppApiClient


@pytest.mark.django_db
def test_pinned_region_fixture_is_served_and_reused():
    seed_region_snapshot()
    seed_region_snapshot()
    assert RegionMapSnapshot.objects.count() == 1
    assert RegionMapFile.objects.count() == 1
    response = AppApiClient().get(reverse("region-map-index"), HTTP_ACCEPT_ENCODING="identity")
    assert response.status_code == 200
    assert response["ETag"] == f'"{CHECKSUM}"'
    assert len(response.json()["regions"]) == 849


@pytest.mark.django_db
def test_pinned_region_fixture_rejects_stale_database():
    RegionMapSnapshot.objects.create(checksum="a" * 64)
    with pytest.raises(ValueError, match="recreate the performance database"):
        seed_region_snapshot()


@pytest.mark.django_db
def test_pinned_region_fixture_rejects_modified_input(tmp_path):
    fixture = tmp_path / "index.json.gz"
    fixture.write_bytes(gzip.compress(b'{"regions":[]}'))
    with patch("perf.region_fixture.FIXTURE", fixture), pytest.raises(ValueError, match="checksum mismatch"):
        seed_region_snapshot()
    assert not RegionMapSnapshot.objects.exists()
