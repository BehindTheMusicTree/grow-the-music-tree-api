import pytest
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator

from grow.model.history.HistoryAction import HistoryAction
from grow.openapi.views import CachedSchemaView


@pytest.fixture(scope="module")
def schema() -> dict:
    return SchemaGenerator().get_schema(request=None, public=True)


def test_history_action_enum_lists_every_action(schema):
    """Clients generate their `action` type from this enum, so it must follow the model."""
    assert schema["components"]["schemas"]["HistoryAction"]["enum"] == [a.value for a in HistoryAction]


def _ok_body(schema: dict, path: str, method: str = "get") -> dict:
    return schema["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]


@pytest.mark.parametrize("path", ["/v1/genres/{uuid}/history/", "/v1/library/songs/{uuid}/history/"])
def test_history_returns_a_bare_list_of_typed_entries(schema, path):
    body = _ok_body(schema, path)
    assert body["type"] == "array"
    assert body["items"]["$ref"].endswith("/HistoryEntryDetailed")
    assert [p["name"] for p in schema["paths"][path]["get"]["parameters"]] == ["uuid"]


@pytest.mark.parametrize(
    "path",
    [
        "/v1/genres/search/",
        "/v1/genres/name-conflicts/",
        "/v1/genres/{uuid}/link-suggestions/",
        "/v1/library/songs/search/",
        "/v1/artists/search/",
        "/v1/artists/{uuid}/genre-counts/",
    ],
)
def test_unpaginated_actions_are_documented_as_arrays(schema, path):
    """These actions answer a bare list: neither the pagination envelope nor the list filters apply."""
    assert _ok_body(schema, path)["type"] == "array"
    names = {p["name"] for p in schema["paths"][path]["get"].get("parameters", [])}
    assert not names & {"page", "page_size", "ordering", "created_on"}


def test_unimplemented_model_actions_are_not_documented(schema):
    """Albums implement list, retrieve and destroy: the kit routes the other verbs but answers 405."""
    assert set(schema["paths"]["/v1/albums/"]) == {"get"}
    assert set(schema["paths"]["/v1/albums/{uuid}/"]) == {"get", "delete"}


def test_both_authentication_schemes_are_declared(schema):
    schemes = schema["components"]["securitySchemes"]
    assert schemes["googleIdToken"]["scheme"] == "bearer"
    assert (schemes["apiKey"]["in"], schemes["apiKey"]["name"]) == ("header", "X-API-Key")


def test_schema_route_is_public_and_serves_the_api(client):
    response = client.get("/schema/")
    assert response.status_code == 200
    assert "/v1/albums/" in response.content.decode()


def test_schema_is_generated_once_per_process(client):
    client.get("/schema/")
    first = CachedSchemaView._schema
    client.get("/schema/")
    assert first is not None
    assert CachedSchemaView._schema is first


def test_genre_operations_have_typed_responses(schema):
    paths = schema["paths"]
    assert "202" in paths["/v1/genres/graph/import-runs/"]["post"]["responses"]
    assert "409" in paths["/v1/genres/graph/import-runs/"]["post"]["responses"]
    for path in ("/v1/genres/graph/", "/v1/genres/tree/", "/v1/genres/{uuid}/alias-of/"):
        assert paths[path], path
    tree_params = {p["name"] for p in paths["/v1/genre-playlists/tree/"]["get"]["parameters"]}
    assert "tree_name" in tree_params


def test_library_viewsets_generate_without_errors():
    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)
    views = ("SongViewSet", "ArtistViewSet", "AlbumViewSet", "RegionMapViewSet")
    errors = [message for message in GENERATOR_STATS._error_cache if any(f"[{view}]" in message for view in views)]
    GENERATOR_STATS.reset()
    assert errors == []


@pytest.mark.parametrize(
    "runs", ["/v1/library/songs/songs/import-runs/", "/v1/artists/import-runs/", "/v1/regions/map/import-runs/"]
)
def test_import_run_protocol_is_typed(schema, runs):
    paths = schema["paths"]
    create = paths[runs]["post"]
    assert set(create["responses"]) == {"201"}
    created = create["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
    assert created.endswith("/ImportRunCreated")
    part = paths[f"{runs}{{run_id}}/parts/{{part}}/"]["put"]
    assert "application/x-ndjson" in part["requestBody"]["content"]
    assert {p["name"]: p["schema"]["type"] for p in part["parameters"]} == {"run_id": "integer", "part": "integer"}
    assert set(paths[f"{runs}{{run_id}}/deletions/"]["put"]["responses"]) == {"200"}
    assert set(paths[f"{runs}{{run_id}}/commit/"]["post"]["responses"]) == {"202"}


def test_song_import_run_declares_its_reviewed_revisions(schema):
    create = schema["paths"]["/v1/library/songs/songs/import-runs/"]["post"]
    request = create["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    body = schema["components"]["schemas"][request]
    assert set(body["required"]) == {"graphRevision", "membershipRevision", "expectedParts"}
    assert "/v1/library/songs/songs/import-runs/{run_id}/assignments/parts/{part}/" in schema["paths"]


def test_song_list_documents_the_optional_total_envelope(schema):
    operation = schema["paths"]["/v1/library/songs/"]["get"]
    assert {"with_total", "cursor", "page", "page_size"} <= {p["name"] for p in operation["parameters"]}
    envelope = schema["components"]["schemas"][_ok_body(schema, "/v1/library/songs/")["$ref"].rsplit("/", 1)[-1]]
    properties = envelope["properties"]
    assert set(properties) == {"overallTotal", "next", "previous", "results", "page", "pageSize", "totalPages"}
    assert properties["overallTotal"]["nullable"] and properties["page"]["nullable"]


def test_song_curation_operations_are_typed(schema):
    paths = schema["paths"]
    patch = paths["/v1/library/songs/{uuid}/"]["patch"]
    assert patch["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/PatchedSongYoutubePatch")
    assert _ok_body(schema, "/v1/library/songs/{uuid}/", "patch")["$ref"].endswith("/SongFull")
    assign = _ok_body(schema, "/v1/library/songs/assign-genre/", "post")["$ref"].rsplit("/", 1)[-1]
    assert set(schema["components"]["schemas"][assign]["properties"]) == {"previous", "undoToken"}
    assert set(paths["/v1/library/songs/assign-genre/undo/"]["post"]["responses"]) == {"204"}
    assert set(paths["/v1/library/songs/{uuid}/"]["delete"]["responses"]) == {"204"}
