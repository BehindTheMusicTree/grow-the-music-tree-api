import json
from copy import deepcopy
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from the_music_tree_genre_kit.criteria.selection.coverage import CriteriaCoverage
from the_music_tree_genre_kit.genre_graph.graph import GraphValidationError
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphAttributionRevision
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict, select_tracks

from grow.authentication.ApiKeyAuthentication import PipelineUser
from grow.authentication.Principal import Principal
from grow.filtering.set.song.SongFilterSet import SongFilterSet
from grow.genre_graph.models import GenreGraphAssignmentBackup, GenreGraphImport
from grow.genre_graph.selection import select_songs
from grow.genre_graph.service import (
    import_reference_graph,
    reference_dataset,
    restore_reference_graph,
    write_song_attributions,
)
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.song.Song import Song
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parents[2] / "fixtures/genre_graph/regional-v2.json").read_text())


def import_graph(payload, mapping=None, revision=None):
    CurationSyncState.objects.update_or_create(
        pk=1, defaults={"exported_on": parse_datetime(payload["curationExportedOn"])}
    )
    return import_reference_graph(
        payload=payload,
        mapping=mapping if mapping is not None else {node["id"]: None for node in payload["nodes"]},
        expected_revision=revision,
        curation_exported_on=payload["curationExportedOn"],
    )


def test_e03_preserves_bindings_songs_duplicate_labels_and_retry(payload):
    factory = ModelFixtureFactory(None)
    dub = factory.create_genre("Dub")
    song = factory.create_song("Assigned", dub)
    genreless = factory.create_song("Unknown", None, youtube_video_id=None)
    mapping = {node["id"]: None for node in payload["nodes"]}
    mapping["LOCAL:dub"] = str(dub.pk)
    dataset = import_graph(payload, mapping)
    dub.refresh_from_db()
    assert dub.graph_node.identity == "LOCAL:dub"
    assert Song.objects.filter(pk__in=[song.pk, genreless.pk]).count() == 2
    assert Genre.objects.filter(_name="Dub").count() == 4
    assert list(GenreGraphAttribution.objects.values_list("track_id", "node__identity")) == [(song.pk, "LOCAL:dub")]
    assert GenreGraphAssignmentBackup.objects.count() == 2
    assert import_graph(payload, mapping, dataset.revision).revision == dataset.revision
    assert GenreGraphImport.objects.count() == 1
    assert list(select_tracks(Song.objects.all(), key="grow", identity="LOCAL:dub")) == [song]
    assert not select_tracks(Song.objects.all(), key="grow", identity="LOCAL:jamaica").exists()


def test_e02_missing_mapping_and_revision_rejected_atomically(payload):
    factory = ModelFixtureFactory(None)
    factory.create_genre("Unmapped")
    with pytest.raises(GraphValidationError, match="Unmapped"):
        import_graph(payload)
    with pytest.raises(GraphValidationError, match="explicit identity mapping"):
        reference_dataset()
    assert GenreGraphImport.objects.count() == 0
    assert Genre.objects.count() == 1


def test_e03_identity_cannot_be_rebound(payload):
    dataset = import_graph(payload)
    mapping = dict(GenreGraphImport.objects.get(pk=dataset.revision).mapping)
    mapping["LOCAL:dub"] = mapping["LOCAL:reggae"]
    with pytest.raises(GraphValidationError, match="rebind"):
        import_graph(payload, mapping, dataset.revision)
    with pytest.raises(GraphRevisionConflict):
        import_graph(payload)


def test_e02_invalid_graph_keeps_original(payload):
    dataset = import_graph(payload)
    changed = deepcopy(payload)
    changed["nodes"][0]["canonicalState"] = "canonical"
    mapping = GenreGraphImport.objects.get(pk=dataset.revision).mapping
    with pytest.raises(GraphValidationError):
        import_graph(changed, mapping, dataset.revision)
    assert reference_dataset().revision == dataset.revision


def test_e03_input_order_does_not_create_revision(payload):
    dataset = import_graph(payload)
    shuffled = deepcopy(payload)
    for field in ("nodes", "relations", "boundaries"):
        shuffled[field].reverse()
    mapping = GenreGraphImport.objects.get(pk=dataset.revision).mapping
    replay = import_graph(shuffled, mapping, dataset.revision)
    assert replay.revision == dataset.revision
    assert replay.membership_revision == dataset.membership_revision
    assert GenreGraphImport.objects.count() == 1


def test_e03_restore_updates_projection_and_keeps_songs(payload):
    factory = ModelFixtureFactory(None)
    dub = factory.create_genre("Dub")
    song = factory.create_song("Assigned", dub)
    mapping = {node["id"]: None for node in payload["nodes"]}
    mapping["LOCAL:dub"] = str(dub.pk)
    original = import_graph(payload, mapping)
    mapping = GenreGraphImport.objects.get(pk=original.revision).mapping
    changed = deepcopy(payload)
    for node in changed["nodes"]:
        if node["id"] == "LOCAL:dub":
            node["name"] = "Renamed dub"
            node["displayParentId"] = "LOCAL:reggae"
    updated = import_graph(changed, mapping, original.revision)
    dub.refresh_from_db()
    assert dub.name == "Renamed dub"
    assert dub.parent_id == Genre.objects.get(graph_node__identity="LOCAL:reggae").pk
    restored = restore_reference_graph(revision=original.revision, expected_revision=updated.revision)
    dub.refresh_from_db()
    assert restored.revision != updated.revision
    assert restored.payload == original.payload
    assert dub.name == "Dub"
    assert dub.parent_id is None
    assert dub.root_id == dub.pk
    assert list(select_tracks(Song.objects.all(), key="grow", identity="LOCAL:dub")) == [song]
    with pytest.raises(GraphRevisionConflict):
        restore_reference_graph(revision=original.revision, expected_revision=updated.revision)


def test_e02_requires_singletons_and_matching_provenance(payload):
    CurationSyncState.objects.filter(pk=1).delete()
    with pytest.raises(GraphValidationError, match="singletons"):
        import_reference_graph(
            payload=payload, mapping={}, expected_revision=None, curation_exported_on=payload["curationExportedOn"]
        )
    CurationSyncState.objects.create(pk=1, exported_on=parse_datetime(payload["curationExportedOn"]))
    with pytest.raises(GraphValidationError, match="provenance"):
        import_reference_graph(
            payload=payload, mapping={}, expected_revision=None, curation_exported_on="2026-11-13T00:00:00Z"
        )
    with pytest.raises(GraphValidationError, match="explicit identity mapping"):
        reference_dataset()


def test_e04_membership_tokens_prevent_lost_attribution_edits(payload):
    song = ModelFixtureFactory(None).create_song("Unknown", None)
    dataset = import_graph(payload)
    provenance = {"decisionId": "test", "source": "synthetic fixture", "rationale": "Explicit attribution"}
    updated = write_song_attributions(
        song_id=song.pk,
        attributions={"LOCAL:dub": provenance},
        expected_revision=dataset.revision,
        expected_membership_revision=dataset.membership_revision,
    )
    assert updated.membership_revision != dataset.membership_revision
    with pytest.raises(GraphRevisionConflict, match="memberships changed"):
        write_song_attributions(
            song_id=song.pk,
            attributions={},
            expected_revision=dataset.revision,
            expected_membership_revision=dataset.membership_revision,
        )
    assert list(select_tracks(Song.objects.all(), key="grow", identity="LOCAL:dub")) == [song]
    with pytest.raises(GraphValidationError, match="provenance"):
        write_song_attributions(
            song_id=song.pk,
            attributions={"LOCAL:dub": {}},
            expected_revision=updated.revision,
            expected_membership_revision=updated.membership_revision,
        )
    assert reference_dataset().membership_revision == updated.membership_revision


def graph_client(role):
    client = APIClient()
    client.force_authenticate(user=PipelineUser(), token=Principal(role=role, email=None, sub=None))
    return client


def test_e01_graph_endpoint_round_trip_permissions_and_conflict(payload):
    CurationSyncState.objects.update_or_create(
        pk=1, defaults={"exported_on": parse_datetime(payload["curationExportedOn"])}
    )
    url = reverse("reference-graph")
    body = {"graph": payload, "mapping": {node["id"]: None for node in payload["nodes"]}, "expectedRevision": None}
    assert APIClient().put(url, body, format="json").status_code == 401
    assert graph_client("viewer").put(url, body, format="json").status_code == 403
    assert graph_client("curator").put(url, body, format="json").status_code == 403
    response = graph_client("pipeline").put(url, body, format="json")
    assert response.status_code == 200, response.data
    loaded = APIClient().get(url)
    assert loaded.status_code == 200
    result = loaded.json()
    assert result["revision"] == response.json()["revision"]
    assert result["graph"]["contractVersion"] == 2
    assert {node["id"] for node in result["graph"]["nodes"]} == set(body["mapping"])
    assert all(result["mapping"].values())
    assert graph_client("pipeline").put(url, body, format="json").status_code == 409
    body["expectedRevision"] = result["revision"]
    body["mapping"] = result["mapping"]
    assert graph_client("pipeline").put(url, body, format="json").json() == response.json()


def test_e01_attributions_endpoint_reduction_refinement_restore_and_permissions(payload):
    song = ModelFixtureFactory(None).create_song("Unknown", None)
    dataset = import_graph(payload)
    url = reverse("song-attributions", kwargs={"song_id": song.pk})
    original = APIClient().get(url)
    assert original.status_code == 200, original.data
    provenance = {"decisionId": "test", "source": "synthetic fixture", "rationale": "Explicit attribution"}
    body = {
        "expectedRevision": str(dataset.revision),
        "expectedMembershipRevision": str(dataset.membership_revision),
        "attributions": {"LOCAL:france": provenance, "LOCAL:french-dub": provenance},
    }
    assert graph_client("pipeline").put(url, body, format="json").status_code == 403
    curator = graph_client("curator")
    updated = curator.put(url, body, format="json")
    assert updated.status_code == 200, updated.data
    assert APIClient().get(url).json()["effectiveAttributions"] == ["LOCAL:french-dub"]
    assert not APIClient().get(url).json()["needsRefinement"]
    assert curator.put(url, body, format="json").status_code == 409
    archived = GenreGraphAttributionRevision.objects.filter(track_id=song.pk, attributions={}).get()
    restore_url = reverse("song-attributions-restore", kwargs={"song_id": song.pk})
    restore_body = {
        "revision": str(archived.revision),
        "expectedRevision": updated.json()["revision"],
        "expectedMembershipRevision": updated.json()["membershipRevision"],
    }
    restored = curator.post(restore_url, restore_body, format="json")
    assert restored.status_code == 200, restored.data
    assert APIClient().get(url).json()["attributions"] == {}


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("canonical", {"style", "scoped", "overlap"}),
        ("regional", {"scoped", "overlap", "exited"}),
        ("all", {"style", "scoped", "overlap", "exited"}),
    ],
)
def test_song_filter_uses_semantic_memberships_without_display_edges(payload, scope, expected):

    factory = ModelFixtureFactory(None)
    songs = {name: factory.create_song(name, None) for name in ("style", "scoped", "overlap", "exited", "unknown")}
    dataset = import_graph(payload)
    provenance = {"decisionId": "test", "source": "fixture", "rationale": "Explicit test assignment"}
    for name, identities in {
        "style": ["LOCAL:dub"],
        "exited": ["LOCAL:french-reggae"],
        "scoped": ["LOCAL:french-dub"],
        "overlap": ["LOCAL:dub", "LOCAL:french-dub", "LOCAL:british-dub"],
    }.items():
        dataset = write_song_attributions(
            song_id=songs[name].pk,
            attributions=dict.fromkeys(identities, provenance),
            expected_revision=dataset.revision,
            expected_membership_revision=dataset.membership_revision,
        )
    genre = Genre.objects.get(graph_node__identity="LOCAL:reggae")
    selected = SongFilterSet({"genre": str(genre.pk), "subgenres": scope}, queryset=Song.objects.all()).qs
    assert set(selected.values_list("title", flat=True)) == expected
    assert selected.count() == len(expected)


def test_song_selection_requires_graph_and_identity_mapping(payload):

    genre = ModelFixtureFactory(None).create_genre("Unmapped")
    with pytest.raises(ValidationError, match="explicit identity mapping"):
        select_songs(Song.objects.all(), genre_id=genre.pk, coverage=CriteriaCoverage.ONLY)
    import_graph(
        payload, {node["id"]: str(genre.pk) if node["id"] == "LOCAL:dub" else None for node in payload["nodes"]}
    )
    Genre.objects.filter(pk=genre.pk).update(graph_node=None)
    with pytest.raises(ValidationError, match="identity mapping"):
        select_songs(Song.objects.all(), genre_id=genre.pk, coverage=CriteriaCoverage.ONLY)


def test_song_list_and_cursor_include_graph_only_assignments(payload):
    factory = ModelFixtureFactory(None)
    songs = [factory.create_song(f"Graph song {index}", None) for index in range(3)]
    dataset = import_graph(payload)
    provenance = {"decisionId": "test", "source": "fixture", "rationale": "Graph-only attribution"}
    for song in songs:
        dataset = write_song_attributions(
            song_id=song.pk,
            attributions={"LOCAL:french-dub": provenance},
            expected_revision=dataset.revision,
            expected_membership_revision=dataset.membership_revision,
        )
    genre = Genre.objects.get(graph_node__identity="LOCAL:france")
    client = APIClient()
    url = reverse("song-list") + f"?genre={genre.pk}&with_total=false&page_size=1"
    seen = []
    while url:
        response = client.get(url)
        assert response.status_code == 200, response.data
        body = response.json()
        seen.extend(row["uuid"] for row in body["results"])
        url = body["next"]
    assert seen == sorted(str(song.pk) for song in songs)
