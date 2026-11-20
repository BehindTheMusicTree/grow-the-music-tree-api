from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework import status

from grow.model.curation.CurationExport import CurationExport
from grow.model.curation.CurationSyncState import CurationSyncState


def export_curation(pipeline_client) -> str:
    """Fetches the curation export as the pipeline does, returning its `exported_on` for the tree import."""
    response = pipeline_client.get(path=reverse("curation-export"))
    assert response.status_code == status.HTTP_200_OK, response.content
    return response.json()["exported_on"]


def record_export(exported_on, canonical_roots=()):
    """Stores an export as `GET curation/export/` would, for a graph or tree built from it."""
    CurationSyncState.load()
    when = parse_datetime(exported_on) if isinstance(exported_on, str) else exported_on
    snapshot = {"canonical_roots": [{"item_id": item_id} for item_id in canonical_roots]}
    return CurationExport.objects.update_or_create(exported_on=when, defaults={"snapshot": snapshot})[0]


def record_graph_export(payload):
    """Stores the export a regional graph payload claims to come from, with the roots it declares."""
    return record_export(payload["curationExportedOn"], [root["nodeId"] for root in payload["canonicalRoots"]])
