from django.urls import reverse
from rest_framework import status


def export_curation(pipeline_client) -> str:
    """Fetches the curation export as the pipeline does, returning its `exported_on` for the tree import."""
    response = pipeline_client.get(path=reverse("curation-export"))
    assert response.status_code == status.HTTP_200_OK, response.content
    return response.json()["exported_on"]
