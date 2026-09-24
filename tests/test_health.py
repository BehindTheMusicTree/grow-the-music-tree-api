import tomllib

import pytest
from django.conf import settings


@pytest.mark.django_db
def test_health_check_returns_ok(client):
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.django_db
def test_health_version_matches_pyproject(client):
    with open(settings.BASE_DIR / "pyproject.toml", "rb") as f:
        expected = tomllib.load(f)["project"]["version"]

    assert client.get("/health/").json()["version"] == expected
