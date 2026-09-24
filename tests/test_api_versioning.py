import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_v1_endpoint_answers(client):
    assert client.get("/v1/genres/").status_code == 200


@pytest.mark.django_db
def test_removed_v0_namespace_returns_404(client):
    assert client.get("/v0/genres/").status_code == 404


def test_reverse_resolves_to_v1():
    assert reverse("genre-list") == "/v1/genres/"
