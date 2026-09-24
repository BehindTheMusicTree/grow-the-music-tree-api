import pytest
from django.urls import reverse


@pytest.mark.django_db
@pytest.mark.parametrize("root", ["/v1/", "/v0/"])
def test_same_endpoint_answers_on_v1_and_v0(client, root):
    response = client.get(f"{root}genres/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_v0_responses_carry_deprecation_headers(client):
    response = client.get("/v0/genres/")

    assert response["Deprecation"].startswith("@")
    assert response["Sunset"].endswith(" GMT")


@pytest.mark.django_db
def test_v1_responses_have_no_deprecation_headers(client):
    response = client.get("/v1/genres/")

    assert "Deprecation" not in response
    assert "Sunset" not in response


def test_reverse_resolves_to_v1():
    assert reverse("genre-list") == "/v1/genres/"
