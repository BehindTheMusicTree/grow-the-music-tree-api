import json
from copy import deepcopy
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.criteria.selection.coverage import CriteriaCoverage
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType
from the_music_tree_genre_kit.genre_graph.assignments import assignment_snapshot
from the_music_tree_genre_kit.genre_graph.models import (
    GenreGraphAssignmentState,
    GenreGraphAttribution,
    GenreGraphAttributionRevision,
    GenreGraphDataset,
    GenreGraphNode,
)
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict, select_tracks

from grow.authentication.ApiKeyAuthentication import PipelineUser
from grow.authentication.Principal import Principal
from grow.filtering.set.song.SongFilterSet import SongFilterSet
from grow.genre_graph import service
from grow.genre_graph.models import GenreGraphAssignmentBackup, GenreGraphImport
from grow.genre_graph.selection import select_songs
from grow.genre_graph.service import (
    import_reference_graph,
    reference_dataset,
    restore_initial_assignments,
    restore_reference_graph,
    restore_song_attributions,
    write_song_attributions,
)
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationExport import CurationExport
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.Song import Song
from tests.utils.curation_export import record_export, record_graph_export
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def reference_configuration(db):
    # Response snapshots must own their transaction; transaction tests flush migration seeds.
    CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
    GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
    if not GenrePlaylist.objects.filter(user=None, criteria=None).exists():
        GenrePlaylist.objects.create(user=None, criteria=None, type_id=0)


def assignment_revision(song_id):
    return (
        GenreGraphAssignmentState.objects.filter(dataset_id="grow", track_id=song_id)
        .values_list("revision", flat=True)
        .first()
    )


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parents[2] / "fixtures/genre_graph/regional-v2.json").read_text())


def import_graph(payload, mapping=None, revision=None):
    record_graph_export(payload)
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
    assert list(select_tracks(Song.objects.all(), node=_node("LOCAL:dub"))) == [song]
    assert not select_tracks(Song.objects.all(), node=_node("LOCAL:jamaica")).exists()


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
    for field in ("nodes", "relations", "canonicalRoots"):
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
    assert list(select_tracks(Song.objects.all(), node=_node("LOCAL:dub"))) == [song]
    with pytest.raises(GraphRevisionConflict):
        restore_reference_graph(revision=original.revision, expected_revision=updated.revision)


def test_e02_requires_singletons_and_matching_provenance(payload):
    CurationExport.objects.all().delete()
    with pytest.raises(GraphValidationError, match="singletons"):
        import_reference_graph(
            payload=payload, mapping={}, expected_revision=None, curation_exported_on=payload["curationExportedOn"]
        )
    record_graph_export(payload)
    record_export("2026-11-13T00:00:00Z", [root["nodeId"] for root in payload["canonicalRoots"]])
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
        attributions={"LOCAL:dub": [provenance]},
        expected_revision=dataset.revision,
        expected_membership_revision=dataset.membership_revision,
        expected_assignment_revision=assignment_revision(song.pk),
    )
    assert updated.membership_revision != dataset.membership_revision
    with pytest.raises(GraphRevisionConflict, match="memberships changed"):
        write_song_attributions(
            song_id=song.pk,
            attributions={},
            expected_revision=dataset.revision,
            expected_membership_revision=dataset.membership_revision,
            expected_assignment_revision=assignment_revision(song.pk),
        )
    assert list(select_tracks(Song.objects.all(), node=_node("LOCAL:dub"))) == [song]
    with pytest.raises(GraphValidationError, match="Evidence"):
        write_song_attributions(
            song_id=song.pk,
            attributions={"LOCAL:dub": [{}]},
            expected_revision=updated.revision,
            expected_membership_revision=updated.membership_revision,
            expected_assignment_revision=assignment_revision(song.pk),
        )
    assert reference_dataset().membership_revision == updated.membership_revision


def graph_client(role):
    client = APIClient()
    client.force_authenticate(user=PipelineUser(), token=Principal(role=role, email=None, sub=None))
    return client


def test_e01_graph_endpoint_round_trip_permissions_and_conflict(payload):
    record_graph_export(payload)
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
        "attributions": {"LOCAL:french-dub": [provenance]},
        "expectedAssignmentRevision": original.json()["assignmentRevision"],
    }
    assert graph_client("pipeline").put(url, body, format="json").status_code == 403
    curator = graph_client("curator")
    updated = curator.put(url, body, format="json")
    assert updated.status_code == 200, updated.data
    assert APIClient().get(url).json()["effectiveAttributions"] == ["LOCAL:french-dub"]
    assert not APIClient().get(url).json()["needsRefinement"]
    assert curator.put(url, body, format="json").status_code == 409
    archived = GenreGraphAttributionRevision.objects.get(
        track_id=song.pk, revision=original.json()["assignmentRevision"], attributions={}
    )
    restore_url = reverse("song-attributions-restore", kwargs={"song_id": song.pk})
    restore_body = {
        "revision": str(archived.revision),
        "expectedAssignmentRevision": updated.json()["assignmentRevision"],
        "expectedRevision": updated.json()["revision"],
        "expectedMembershipRevision": updated.json()["membershipRevision"],
    }
    restored = curator.post(restore_url, restore_body, format="json")
    assert restored.status_code == 200, restored.data
    assert APIClient().get(url).json()["attributions"] == {}


def test_assignment_api_preserves_evidence_and_checks_each_reviewed_token(payload):
    song = ModelFixtureFactory(None).create_song("Multiple evidence", None)
    import_graph(payload)
    url = reverse("song-attributions", kwargs={"song_id": song.pk})
    reader = APIClient()
    curator = graph_client("curator")
    original = reader.get(url).json()
    evidence = [
        {"decisionId": decision, "source": "synthetic fixture", "rationale": "Independent positive evidence"}
        for decision in ("second", "first")
    ]

    def body(snapshot, attributions):
        return {
            "expectedRevision": snapshot["revision"],
            "expectedMembershipRevision": snapshot["membershipRevision"],
            "expectedAssignmentRevision": snapshot["assignmentRevision"],
            "attributions": attributions,
        }

    response = curator.put(url, body(original, {"LOCAL:french-dub": evidence}), format="json")
    assert response.status_code == 200, response.data
    written = reader.get(url).json()
    assert written["attributions"] == {"LOCAL:french-dub": list(reversed(evidence))}
    assert written["assignmentRevision"] != original["assignmentRevision"]
    history_count = GenreGraphAttributionRevision.objects.count()
    # Evidence order is not an edit, so retrying the complete reviewed set is idempotent.
    response = curator.put(url, body(written, {"LOCAL:french-dub": evidence}), format="json")
    assert response.status_code == 200, response.data
    assert reader.get(url).json() == written
    assert GenreGraphAttributionRevision.objects.count() == history_count

    stale_assignment = body(written, {})
    stale_assignment["expectedAssignmentRevision"] = original["assignmentRevision"]
    assert curator.put(url, stale_assignment, format="json").status_code == 409
    stale_population = body(written, {})
    stale_population["expectedMembershipRevision"] = original["membershipRevision"]
    assert curator.put(url, stale_population, format="json").status_code == 409
    conflicting = deepcopy(evidence)
    conflicting[0]["rationale"] = "Changed content for a permanent decision"
    assert curator.put(url, body(written, {"LOCAL:french-dub": conflicting}), format="json").status_code == 400
    assert reader.get(url).json() == written
    assert GenreGraphAttributionRevision.objects.count() == history_count

    response = curator.put(url, body(written, {}), format="json")
    assert response.status_code == 200, response.data
    cleared = reader.get(url).json()
    assert cleared["attributions"] == {}
    assert cleared["assignmentRevision"] != written["assignmentRevision"]
    assert curator.put(url, body(original, {"LOCAL:french-dub": evidence}), format="json").status_code == 409
    restored = curator.post(
        reverse("song-attributions-restore", kwargs={"song_id": song.pk}),
        {**body(cleared, {}), "revision": written["assignmentRevision"]},
        format="json",
    )
    assert restored.status_code == 200, restored.data
    assert reader.get(url).json()["attributions"] == written["attributions"]


@pytest.mark.parametrize("operation", ["write", "restore"])
def test_song_assignment_rejects_multiple_direct_genres_without_mutation(payload, operation):
    song = ModelFixtureFactory(None).create_song("Single genre", None)
    dataset = import_graph(payload)
    url = reverse("song-attributions", kwargs={"song_id": song.pk})
    original = APIClient().get(url).json()
    evidence = {"decisionId": "invalid-multiple", "source": "fixture", "rationale": "Two direct genres"}
    attributions = {"LOCAL:dub": [evidence], "LOCAL:french-dub": [evidence]}
    body = {
        "expectedRevision": original["revision"],
        "expectedMembershipRevision": original["membershipRevision"],
        "expectedAssignmentRevision": original["assignmentRevision"],
    }
    if operation == "restore":
        archived = GenreGraphAttributionRevision.objects.create(
            dataset=dataset,
            track_id=song.pk,
            revision=uuid4(),
            graph_revision=dataset.revision,
            attributions=attributions,
        )
        body["revision"] = str(archived.revision)
        url = reverse("song-attributions-restore", kwargs={"song_id": song.pk})
    else:
        body["attributions"] = attributions
    history_count = GenreGraphAttributionRevision.objects.count()
    response = getattr(graph_client("curator"), "post" if operation == "restore" else "put")(url, body, format="json")
    assert response.status_code == 400, response.data
    assert "at most one" in str(response.data)
    assert APIClient().get(reverse("song-attributions", kwargs={"song_id": song.pk})).json() == original
    assert GenreGraphAttributionRevision.objects.count() == history_count
    assert not GenreGraphAttribution.objects.filter(track=song).exists()


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("canonical", {"style"}),
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
        "overlap": ["LOCAL:french-dub"],
    }.items():
        dataset = write_song_attributions(
            song_id=songs[name].pk,
            attributions={identity: [provenance] for identity in identities},
            expected_revision=dataset.revision,
            expected_membership_revision=dataset.membership_revision,
            expected_assignment_revision=assignment_revision(songs[name].pk),
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
    with pytest.raises(IntegrityError, match="Permanent graph binding"), transaction.atomic():
        Genre.objects.filter(pk=genre.pk).update(graph_node=None)
    assert not select_songs(Song.objects.all(), genre_id=genre.pk, coverage=CriteriaCoverage.ONLY).exists()


def test_song_list_keeps_unassigned_and_unplayable_songs(payload):
    factory = ModelFixtureFactory(None)
    songs = [factory.create_song(f"Unassigned {index}", None, youtube_video_id=None) for index in range(2)]
    dataset = import_graph(payload)
    response = APIClient().get(reverse("song-list") + "?with_total=false&page=1")
    assert response.status_code == 200, response.content
    assert {row["uuid"] for row in response.json()["results"]} == {str(song.pk) for song in songs}
    assert response["X-Genre-Membership-Revision"] == str(dataset.membership_revision)


def test_song_list_and_cursor_include_graph_only_assignments(payload):
    factory = ModelFixtureFactory(None)
    songs = [factory.create_song(f"Graph song {index}", None) for index in range(3)]
    dataset = import_graph(payload)
    provenance = {"decisionId": "test", "source": "fixture", "rationale": "Graph-only attribution"}
    for song in songs:
        dataset = write_song_attributions(
            song_id=song.pk,
            attributions={"LOCAL:french-dub": [provenance]},
            expected_revision=dataset.revision,
            expected_membership_revision=dataset.membership_revision,
            expected_assignment_revision=assignment_revision(song.pk),
        )
    genre = Genre.objects.get(graph_node__identity="LOCAL:france")
    client = APIClient()
    url = reverse("song-list") + f"?genre={genre.pk}&with_total=false&page_size=1"
    seen = []
    while url:
        response = client.get(url)
        assert response.status_code == 200, response.data
        assert response["X-Genre-Graph-Revision"] == str(dataset.revision)
        assert response["X-Genre-Membership-Revision"] == str(dataset.membership_revision)
        body = response.json()
        seen.extend(row["uuid"] for row in body["results"])
        url = body["next"]
    assert seen == sorted(str(song.pk) for song in songs)


def test_graph_import_preserves_existing_pop_child(payload):
    factory = ModelFixtureFactory(None)
    parent = factory.create_genre("Reggae")
    child = factory.create_genre("Dub", parent=parent)
    child.side = "pop"
    child.save()
    song = factory.create_song("Existing song", child)
    mapping = {node["id"]: None for node in payload["nodes"]}
    mapping.update({"LOCAL:reggae": str(parent.pk), "LOCAL:dub": str(child.pk)})
    graph = deepcopy(payload)
    next(node for node in graph["nodes"] if node["id"] == "LOCAL:dub")["displayParentId"] = "LOCAL:reggae"
    import_graph(graph, mapping)
    child.refresh_from_db()
    assert child.side == "pop"
    assert child.parent_id == parent.pk
    assert child.root_id == parent.pk
    assert list(select_tracks(Song.objects.all(), node=_node("LOCAL:dub"))) == [song]


def _node(identity):
    return GenreGraphNode.objects.get(dataset_id="grow", identity=identity)


def _canonical_root(identity):
    return {
        "nodeId": identity,
        "provenance": {"decisionId": f"root-{identity}", "source": "test", "rationale": "Synthetic canonical root."},
    }


def _without_identity(payload, identity):
    changed = deepcopy(payload)
    changed["nodes"] = [node for node in changed["nodes"] if node["id"] != identity]
    changed["relations"] = [row for row in changed["relations"] if identity not in (row["childId"], row["parentId"])]
    changed["canonicalRoots"] = [row for row in changed["canonicalRoots"] if row["nodeId"] != identity]
    return _with_own_export(changed)


def _with_own_export(changed):
    """A graph with other roots comes from another export; reusing the date would overwrite the original's snapshot."""
    changed["curationExportedOn"] = (parse_datetime(changed["curationExportedOn"]) + timedelta(days=1)).isoformat()
    record_graph_export(changed)
    return changed


def _retirement(target):
    return {
        "target": target,
        "provenance": {
            "decisionId": "retire-fixture",
            "source": "fixture",
            "rationale": "Explicit synthetic retirement",
        },
    }


@pytest.mark.parametrize("target", [None, "LOCAL:dub", "LOCAL:reggae"])
def test_retirement_snapshots_and_reactivation_preserve_duplicate_label_uuid(payload, target):
    original = import_graph(payload)
    retired = Genre.objects.get(semantic_identity="LOCAL:french-dub")
    retained = Genre.objects.get(semantic_identity="LOCAL:dub")
    song = ModelFixtureFactory(None).create_song("Retired expression", None)
    provenance = {"decisionId": "assign", "source": "fixture", "rationale": "Direct regional expression"}
    assigned = write_song_attributions(
        song_id=song.pk,
        attributions={"LOCAL:french-dub": [provenance]},
        expected_revision=original.revision,
        expected_membership_revision=original.membership_revision,
        expected_assignment_revision=assignment_revision(song.pk),
    )
    changed = _without_identity(payload, "LOCAL:french-dub")
    mapping = dict(GenreGraphImport.objects.get(pk=original.revision).mapping)
    del mapping["LOCAL:french-dub"]
    updated = import_reference_graph(
        payload=changed,
        mapping=mapping,
        expected_revision=assigned.revision,
        curation_exported_on=changed["curationExportedOn"],
        retirements={"LOCAL:french-dub": _retirement(target)},
    )
    retired.refresh_from_db()
    assert retired.graph_node_id is not None
    assert not retired.graph_node.is_active
    assert retired.semantic_identity == "LOCAL:french-dub"
    assert Genre.objects.get(pk=retained.pk).name == retired.name == "Dub"
    expected = {target} if target else set()
    assert set(song.graph_attributions.values_list("node__identity", flat=True)) == expected
    snapshot = GenreGraphAttributionRevision.objects.filter(
        track_id=song.pk, attributions__has_key="LOCAL:french-dub"
    ).latest("created_at")
    assert snapshot.attributions == {"LOCAL:french-dub": [provenance]}
    restored = restore_reference_graph(revision=original.revision, expected_revision=updated.revision)
    retired.refresh_from_db()
    assert retired.graph_node.identity == "LOCAL:french-dub"
    assert Genre.objects.get(semantic_identity="LOCAL:french-dub").pk == retired.pk
    restore_song_attributions(
        song_id=song.pk,
        revision=snapshot.revision,
        expected_revision=restored.revision,
        expected_membership_revision=restored.membership_revision,
        expected_assignment_revision=assignment_revision(song.pk),
    )
    assert assignment_snapshot(dataset=reference_dataset(), track_id=song.pk) == snapshot.attributions
    assert Song.objects.filter(pk=song.pk).exists()


@pytest.mark.parametrize(
    "decisions",
    [{}, {"LOCAL:french-dub": {"target": None}}, {"LOCAL:french-dub": _retirement("LOCAL:missing")}],
)
def test_retirement_requires_complete_valid_decisions_atomically(payload, decisions):
    original = import_graph(payload)
    changed = _without_identity(payload, "LOCAL:french-dub")
    mapping = dict(GenreGraphImport.objects.get(pk=original.revision).mapping)
    del mapping["LOCAL:french-dub"]
    with pytest.raises(GraphValidationError):
        import_reference_graph(
            payload=changed,
            mapping=mapping,
            expected_revision=original.revision,
            curation_exported_on=changed["curationExportedOn"],
            retirements=decisions,
        )
    assert reference_dataset().revision == original.revision
    assert Genre.objects.get(semantic_identity="LOCAL:french-dub").graph_node_id is not None
    assert GenreGraphImport.objects.count() == 1


def test_restore_older_graph_requires_decision_for_added_concept(payload):
    original = import_graph(payload)
    changed = deepcopy(payload)
    changed["nodes"].append({"id": "LOCAL:added", "name": "Dub", "kind": "genre"})
    changed["canonicalRoots"].append(_canonical_root("LOCAL:added"))
    _with_own_export(changed)
    mapping = {**GenreGraphImport.objects.get(pk=original.revision).mapping, "LOCAL:added": None}
    updated = import_graph(changed, mapping, original.revision)
    added = Genre.objects.get(semantic_identity="LOCAL:added")
    with pytest.raises(GraphValidationError, match="Retirements"):
        restore_reference_graph(revision=original.revision, expected_revision=updated.revision)
    restored = restore_reference_graph(
        revision=original.revision,
        expected_revision=updated.revision,
        retirements={"LOCAL:added": _retirement(None)},
    )
    added.refresh_from_db()
    assert added.graph_node_id is not None
    assert not added.graph_node.is_active
    assert restored.payload == original.payload
    reactivated = restore_reference_graph(revision=updated.revision, expected_revision=restored.revision)
    assert reactivated.payload == updated.payload
    assert Genre.objects.get(semantic_identity="LOCAL:added").pk == added.pk


def test_initial_assignment_restore_uses_backup_and_semantic_bindings(payload):
    factory = ModelFixtureFactory(None)
    dub = factory.create_genre("Dub")
    song = factory.create_song("Original assignment", dub)
    unknown = factory.create_song("Originally genreless", None)
    mapping = {node["id"]: None for node in payload["nodes"]}
    mapping["LOCAL:dub"] = str(dub.pk)
    original = import_graph(payload, mapping)
    provenance = {"decisionId": "restore", "source": "fixture", "rationale": "Restore initial explicit mapping"}
    current = original
    for item in (song, unknown):
        current = write_song_attributions(
            song_id=item.pk,
            attributions={"LOCAL:reggae": [provenance]},
            expected_revision=current.revision,
            expected_membership_revision=current.membership_revision,
            expected_assignment_revision=assignment_revision(item.pk),
        )
    # The live single-genre field is deliberately wrong; rollback reads only the archive.
    Song.objects.filter(pk=song.pk).update(genre=None)
    restored = restore_initial_assignments(
        revision=original.revision,
        expected_revision=current.revision,
        expected_membership_revision=current.membership_revision,
        provenance=provenance,
    )
    assert assignment_snapshot(dataset=reference_dataset(), track_id=song.pk) == {"LOCAL:dub": [provenance]}
    assert not unknown.graph_attributions.exists()
    assert Song.objects.filter(pk__in=[song.pk, unknown.pk]).count() == 2
    assert restored.membership_revision != current.membership_revision
    replay = restore_initial_assignments(
        revision=original.revision,
        expected_revision=restored.revision,
        expected_membership_revision=restored.membership_revision,
        provenance=provenance,
    )
    assert replay.membership_revision == restored.membership_revision
    with pytest.raises(GraphRevisionConflict):
        restore_initial_assignments(
            revision=original.revision,
            expected_revision=current.revision,
            expected_membership_revision=current.membership_revision,
            provenance=provenance,
        )


def test_retirement_failure_rolls_back_attributions_history_and_bindings(payload, monkeypatch):
    original = import_graph(payload)
    song = ModelFixtureFactory(None).create_song("Keep during failed retirement", None)
    provenance = _retirement(None)["provenance"]
    current = write_song_attributions(
        song_id=song.pk,
        attributions={"LOCAL:french-dub": [provenance]},
        expected_revision=original.revision,
        expected_membership_revision=reference_dataset().membership_revision,
        expected_assignment_revision=assignment_revision(song.pk),
    )
    changed = _without_identity(payload, "LOCAL:french-dub")
    mapping = dict(GenreGraphImport.objects.get(pk=original.revision).mapping)
    del mapping["LOCAL:french-dub"]
    history_count = GenreGraphAttributionRevision.objects.count()

    def fail_replacement(**kwargs):
        raise RuntimeError("Injected failure after attribution retirement")

    monkeypatch.setattr(service, "replace_graph", fail_replacement)
    with pytest.raises(RuntimeError, match="Injected failure"):
        import_reference_graph(
            payload=changed,
            mapping=mapping,
            expected_revision=current.revision,
            curation_exported_on=changed["curationExportedOn"],
            retirements={"LOCAL:french-dub": _retirement("LOCAL:reggae")},
        )
    assert reference_dataset().revision == current.revision
    assert reference_dataset().membership_revision == current.membership_revision
    assert GenreGraphAttributionRevision.objects.count() == history_count
    assert assignment_snapshot(dataset=reference_dataset(), track_id=song.pk) == {"LOCAL:french-dub": [provenance]}
    assert Genre.objects.get(semantic_identity="LOCAL:french-dub").graph_node_id is not None


def test_reference_graph_identity_binding_at_canonical_tree_scale(payload):
    large = deepcopy(payload)
    large["nodes"].extend(
        {"id": f"LOCAL:scale-{index}", "name": f"Scale {index}", "kind": "genre"}
        for index in range(1710 - len(large["nodes"]))
    )
    large["canonicalRoots"].extend(
        _canonical_root(f"LOCAL:scale-{index}") for index in range(1710 - len(payload["nodes"]))
    )
    original = import_graph(large)
    assert Genre.objects.filter(graph_node__dataset_id="grow").count() == 1710
    mapping = dict(GenreGraphImport.objects.get(pk=original.revision).mapping)
    changed = _without_identity(large, "LOCAL:scale-0")
    retired_uuid = mapping.pop("LOCAL:scale-0")
    updated = import_reference_graph(
        payload=changed,
        mapping=mapping,
        expected_revision=original.revision,
        curation_exported_on=changed["curationExportedOn"],
        retirements={"LOCAL:scale-0": _retirement(None)},
    )
    restored = restore_reference_graph(revision=original.revision, expected_revision=updated.revision)
    assert len(restored.payload["nodes"]) == 1710
    assert str(Genre.objects.get(semantic_identity="LOCAL:scale-0").pk) == retired_uuid


def test_retirement_api_hides_archived_genres_and_playlists(payload):
    original = import_graph(payload)
    retired = Genre.objects.get(semantic_identity="LOCAL:french-dub")
    playlist_id = retired.criteria_playlist.pk
    changed = _without_identity(payload, "LOCAL:french-dub")
    mapping = dict(GenreGraphImport.objects.get(pk=original.revision).mapping)
    del mapping["LOCAL:french-dub"]
    response = graph_client("pipeline").put(
        reverse("reference-graph"),
        {
            "graph": changed,
            "mapping": mapping,
            "expectedRevision": str(original.revision),
            "retirements": {"LOCAL:french-dub": _retirement(None)},
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    client = APIClient()
    for basename, pk in (("genre", retired.pk), ("genre-playlist", playlist_id), ("playlist", playlist_id)):
        assert client.get(reverse(f"{basename}-detail", kwargs={"pk": pk})).status_code == 404
    songs = client.get(reverse("song-list"), {"genre": str(retired.pk)})
    assert songs.status_code == 200, songs.content
    assert songs.json()["results"] == []
    loaded = client.get(reverse("reference-graph")).json()
    assert "LOCAL:french-dub" not in loaded["mapping"]
    assert Genre.objects.filter(pk=retired.pk).exists()


def test_initial_assignments_restore_endpoint_requires_curator_and_revision_tokens(payload):
    song = ModelFixtureFactory(None).create_song("Unassigned before initial import", None)
    initial = import_graph(payload)
    provenance = _retirement(None)["provenance"]
    current = write_song_attributions(
        song_id=song.pk,
        attributions={"LOCAL:dub": [provenance]},
        expected_revision=initial.revision,
        expected_membership_revision=initial.membership_revision,
        expected_assignment_revision=assignment_revision(song.pk),
    )
    url = reverse("reference-graph-assignments-restore")
    body = {
        "revision": str(initial.revision),
        "expectedRevision": str(current.revision),
        "expectedMembershipRevision": str(current.membership_revision),
        "provenance": provenance,
    }
    assert APIClient().post(url, body, format="json").status_code == 401
    assert graph_client("pipeline").post(url, body, format="json").status_code == 403
    response = graph_client("curator").post(url, body, format="json")
    assert response.status_code == 200, response.data
    assert not song.graph_attributions.exists()
    assert graph_client("curator").post(url, body, format="json").status_code == 409


def test_initial_restore_requires_reactivation_and_preserves_later_songs(payload):
    factory = ModelFixtureFactory(None)
    french = factory.create_genre("French Dub")
    song = factory.create_song("Initial song", french)
    mapping = {node["id"]: None for node in payload["nodes"]}
    mapping["LOCAL:french-dub"] = str(french.pk)
    initial = import_graph(payload, mapping)
    later = factory.create_song("Later song", None)
    provenance = _retirement(None)["provenance"]
    current = write_song_attributions(
        song_id=later.pk,
        attributions={"LOCAL:reggae": [provenance]},
        expected_revision=initial.revision,
        expected_membership_revision=reference_dataset().membership_revision,
        expected_assignment_revision=assignment_revision(later.pk),
    )
    changed = _without_identity(payload, "LOCAL:french-dub")
    mapping = dict(GenreGraphImport.objects.get(pk=initial.revision).mapping)
    del mapping["LOCAL:french-dub"]
    retired = import_reference_graph(
        payload=changed,
        mapping=mapping,
        expected_revision=current.revision,
        curation_exported_on=changed["curationExportedOn"],
        retirements={"LOCAL:french-dub": _retirement(None)},
    )
    with pytest.raises(GraphValidationError, match="reactivated"):
        restore_initial_assignments(
            revision=initial.revision,
            expected_revision=retired.revision,
            expected_membership_revision=retired.membership_revision,
            provenance=provenance,
        )
    assert not song.graph_attributions.exists()
    assert set(later.graph_attributions.values_list("node__identity", flat=True)) == {"LOCAL:reggae"}
    reactivated = restore_reference_graph(revision=initial.revision, expected_revision=retired.revision)
    restore_initial_assignments(
        revision=initial.revision,
        expected_revision=reactivated.revision,
        expected_membership_revision=reactivated.membership_revision,
        provenance=provenance,
    )
    assert set(song.graph_attributions.values_list("node__identity", flat=True)) == {"LOCAL:french-dub"}
    assert set(later.graph_attributions.values_list("node__identity", flat=True)) == {"LOCAL:reggae"}


@pytest.mark.parametrize(
    "mutation", ["clear", "rebind", "rename", "delete_criteria", "delete_genre", "move_genre", "mismatch"]
)
def test_database_preserves_permanent_graph_bindings(payload, mutation):
    import_graph(payload)
    genre = Genre.objects.get(semantic_identity="LOCAL:dub")
    other = Genre.objects.get(semantic_identity="LOCAL:french-dub")
    quote = connection.ops.quote_name
    criteria_table = quote(Genre._meta.get_field("graph_node").model._meta.db_table)
    genre_table = quote(Genre._meta.db_table)
    prepared_pk = Genre._meta.get_field("uuid").get_db_prep_value(genre.pk, connection)

    def corrupt():
        with connection.cursor() as cursor:
            mutate(cursor)

    def mutate(cursor):
        if mutation == "clear":
            cursor.execute(
                f"UPDATE {criteria_table} SET graph_node_id = NULL, semantic_identity = NULL WHERE uuid = %s",
                [prepared_pk],
            )
        elif mutation == "rebind":
            cursor.execute(
                f"UPDATE {criteria_table} SET graph_node_id = %s WHERE uuid = %s", [other.graph_node_id, prepared_pk]
            )
        elif mutation == "rename":
            cursor.execute(
                f"UPDATE {criteria_table} SET semantic_identity = 'LOCAL:stolen' WHERE uuid = %s", [prepared_pk]
            )
        elif mutation == "mismatch":
            unbound = ModelFixtureFactory(None).create_genre("Unbound")
            cursor.execute(
                f"UPDATE {criteria_table} SET semantic_identity = 'LOCAL:missing' WHERE uuid = %s",
                [Genre._meta.get_field("uuid").get_db_prep_value(unbound.pk, connection)],
            )
        elif mutation == "delete_criteria":
            cursor.execute(f"DELETE FROM {criteria_table} WHERE uuid = %s", [prepared_pk])
        elif mutation == "move_genre":
            cursor.execute(
                f"UPDATE {genre_table} SET criteria_ptr_id = %s WHERE criteria_ptr_id = %s",
                [Genre._meta.get_field("uuid").get_db_prep_value(other.pk, connection), prepared_pk],
            )
        else:
            cursor.execute(f"DELETE FROM {genre_table} WHERE criteria_ptr_id = %s", [prepared_pk])

    message = "Graph binding must match" if mutation == "mismatch" else "Permanent graph"
    with pytest.raises(IntegrityError, match=message), transaction.atomic():
        corrupt()
    genre.refresh_from_db()
    assert genre.semantic_identity == "LOCAL:dub"
    assert genre.graph_node.identity == "LOCAL:dub"


def test_permanent_binding_migration_rejects_invalid_existing_rows(payload):
    migration = import_module("grow.migrations.0132_permanent_graph_bindings")
    import_graph(payload)
    genre = Genre.objects.get(semantic_identity="LOCAL:dub")
    editor = connection.schema_editor(atomic=False)
    migration.remove_guards(apps, editor)
    try:
        Genre.objects.filter(pk=genre.pk).update(semantic_identity="LOCAL:invalid")
        with pytest.raises(RuntimeError, match="Existing graph binding"):
            migration.install_guards(apps, editor)
    finally:
        Genre.objects.filter(pk=genre.pk).update(semantic_identity="LOCAL:dub")
        migration.install_guards(apps, editor)
    with pytest.raises(IntegrityError, match="Permanent graph"), transaction.atomic():
        Genre.objects.filter(pk=genre.pk).update(graph_node=None)


@pytest.mark.parametrize("dataset_key,identity", [("other", "LOCAL:free"), ("grow", "LOCAL:different")])
def test_unbound_genre_cannot_claim_incompatible_free_node(dataset_key, identity):
    dataset = GenreGraphDataset.objects.create(key=dataset_key, payload={})
    node = GenreGraphNode.objects.create(dataset=dataset, identity=identity, is_umbrella=False)
    genre = ModelFixtureFactory(None).create_genre("Unbound")
    with pytest.raises(IntegrityError, match="Graph binding must match"), transaction.atomic():
        Genre.objects.filter(pk=genre.pk).update(graph_node=node, semantic_identity="LOCAL:free")
    genre.refresh_from_db()
    assert genre.graph_node_id is None
    assert genre.semantic_identity is None


def test_graph_retirement_invalidates_genre_tree_token(payload):
    dataset = import_graph(payload)
    before = GenreTreeVersion.current_token()
    retired = dataset.nodes.get(identity="LOCAL:french-dub")
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {connection.ops.quote_name(retired._meta.db_table)} SET is_active = FALSE WHERE id = %s",
            [retired.pk],
        )
    assert GenreTreeVersion.current_token() != before


def test_empty_initial_assignment_archive_is_valid_and_preserves_later_songs(payload):
    initial = import_graph(payload)
    assert not GenreGraphAssignmentBackup.objects.filter(imported_id=initial.revision).exists()
    song = ModelFixtureFactory(None).create_song("Added after empty initial snapshot", None)
    provenance = _retirement(None)["provenance"]
    current = write_song_attributions(
        song_id=song.pk,
        attributions={"LOCAL:dub": [provenance]},
        expected_revision=initial.revision,
        expected_membership_revision=initial.membership_revision,
        expected_assignment_revision=assignment_revision(song.pk),
    )
    restored = restore_initial_assignments(
        revision=initial.revision,
        expected_revision=current.revision,
        expected_membership_revision=current.membership_revision,
        provenance=provenance,
    )
    assert restored.membership_revision == current.membership_revision
    assert assignment_snapshot(dataset=restored, track_id=song.pk) == {"LOCAL:dub": [provenance]}


def test_graph_import_rejects_roots_differing_from_the_export(payload):
    record_export(payload["curationExportedOn"], ["Q1"])
    with pytest.raises(GraphValidationError, match="canonicalRoots differ"):
        import_reference_graph(
            payload=payload,
            mapping={node["id"]: None for node in payload["nodes"]},
            expected_revision=None,
            curation_exported_on=payload["curationExportedOn"],
        )


def test_graph_import_rejects_an_export_without_snapshot(payload):
    record_graph_export(payload)
    CurationExport.objects.update(snapshot=None)
    with pytest.raises(GraphValidationError, match="predates snapshots"):
        import_reference_graph(
            payload=payload,
            mapping={node["id"]: None for node in payload["nodes"]},
            expected_revision=None,
            curation_exported_on=payload["curationExportedOn"],
        )
