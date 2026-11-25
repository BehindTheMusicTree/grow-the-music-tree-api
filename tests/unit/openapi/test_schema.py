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
    assert not names & {"page", "page_size", "with_total", "cursor", "ordering", "created_on"}


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
    views = (
        "SongViewSet",
        "ArtistViewSet",
        "AlbumViewSet",
        "RegionMapViewSet",
        "TagViewSet",
        "PlaylistViewSet",
        "ManualPlaylistViewSet",
        "CriteriaPlaylistViewSet",
        "TagPlaylistViewSet",
        "GenrePlaylistViewSet",
        "Curation",
    )
    errors = [message for message in GENERATOR_STATS._error_cache if any(f"[{view}" in message for view in views)]
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


def test_region_map_import_run_accepts_only_full_mode(schema):
    create = schema["paths"]["/v1/regions/map/import-runs/"]["post"]
    request = create["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    mode = schema["components"]["schemas"][request]["properties"]["mode"]
    ref = mode.get("$ref") or mode["allOf"][0]["$ref"]
    assert schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]["enum"] == ["full"]


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


@pytest.mark.parametrize(
    "path",
    [
        "/v1/playlists/{uuid}/tracks/",
        "/v1/manual-playlists/{uuid}/tracks/",
        "/v1/tag-playlists/{uuid}/tracks/",
        "/v1/genre-playlists/{uuid}/tracks/",
    ],
)
def test_playlist_tracks_document_only_the_parameters_they_read(schema, path):
    """The tracks action never calls `filter_queryset`: the viewset's filterset parameters do not apply."""
    operation = schema["paths"][path]["get"]
    names = {p["name"] for p in operation["parameters"]}
    assert {"from", "page", "page_size"} <= names
    assert not names & {"ordering", "created_on", "name", "parent"}
    assert "Mix into" not in operation["description"]


def test_tag_destroy_and_overview_are_typed(schema):
    assert set(schema["paths"]["/v1/tags/{uuid}/"]["delete"]["responses"]) == {"204"}
    assert _ok_body(schema, "/v1/tags/{uuid}/overview/")["$ref"].endswith("/CriteriaOverview")


@pytest.mark.parametrize(
    ("path", "page"),
    [
        ("/v1/curation/{list_name}/entries/", "CurationEntriesPage"),
        ("/v1/curation/edges/", "CurationEdgesPage"),
        ("/v1/curation/history/", "CurationHistoryPage"),
    ],
)
def test_paginated_curation_views_document_the_real_envelope(schema, path, page):
    assert _ok_body(schema, path)["$ref"].endswith(f"/{page}")
    properties = schema["components"]["schemas"][page]["properties"]
    assert set(properties) == {
        "overallTotal",
        "next",
        "previous",
        "results",
        "page",
        "pageSize",
        "totalPages",
        "labels",
    }
    names = {p["name"] for p in schema["paths"][path]["get"]["parameters"]}
    assert {"page", "page_size"} <= names


def test_curation_rows_keep_their_snake_case_columns(schema):
    """The renderer skips the `row` subtree, so the schema declares it as a free-form object."""
    row = schema["components"]["schemas"]["CurationRule"]["properties"]["row"]
    assert row["type"] == "object"
    assert "properties" not in row


def test_curation_list_and_detail_operations_have_distinct_ids(schema):
    paths = schema["paths"]
    ids = [
        paths["/v1/curation/{list_name}/entries/"]["get"]["operationId"],
        paths["/v1/curation/{list_name}/entries/{uuid}/"]["get"]["operationId"],
        paths["/v1/curation/edges/"]["get"]["operationId"],
        paths["/v1/curation/edges/{uuid}/"]["get"]["operationId"],
    ]
    assert len(set(ids)) == 4


def test_curation_export_stays_snake_case(schema):
    """The export renders with `JSONRenderer`: its keys are the pipeline's snake_case columns."""
    body = _ok_body(schema, "/v1/curation/export/")
    assert {"exported_on", "genre_alias", "edges", "overview_status_overrides"} <= set(body["properties"])
    assert "exportedOn" not in body["properties"]
    assert "genre_alias_version" not in body["required"]
    assert "target_item_id" not in body["properties"]["genre_alias"]["items"]["required"]
    assert "409" in schema["paths"]["/v1/curation/export/"]["get"]["responses"]


def test_genre_alias_targets_document_the_unpublished_case(schema):
    assert "503" in schema["paths"]["/v1/curation/genre-alias-targets/"]["get"]["responses"]


def _ref(body: dict) -> str:
    return body["$ref"].rsplit("/", 1)[-1]


def test_health_documents_both_outcomes_with_one_typed_body(schema):
    responses = schema["paths"]["/health/"]["get"]["responses"]
    assert set(responses) == {"200", "503"}
    assert {_ref(r["content"]["application/json"]["schema"]) for r in responses.values()} == {"Health"}


@pytest.mark.parametrize(("path", "name"), [("/v1/auth/me/", "AuthMe"), ("/v1/playback/context/", "PlaybackContext")])
def test_auth_me_and_playback_have_typed_bodies(schema, path, name):
    assert _ref(_ok_body(schema, path)) == name


def test_import_run_list_is_the_paginated_envelope_with_a_kind_filter(schema):
    operation = schema["paths"]["/v1/pipeline/imports/"]["get"]
    assert _ref(_ok_body(schema, "/v1/pipeline/imports/")) == "ImportRunPage"
    kind = next(p for p in operation["parameters"] if p["name"] == "kind")
    assert "songs" in kind["schema"]["enum"]
    page = schema["components"]["schemas"]["ImportRunPage"]
    assert {"results", "overallTotal", "totalPages"} <= set(page["properties"])


def test_pipeline_run_outcomes_are_documented(schema):
    paths = schema["paths"]
    assert set(paths["/v1/pipeline/runs/claim/"]["post"]["responses"]) == {"200", "204"}
    assert set(paths["/v1/pipeline/runs/latest/"]["get"]["responses"]) == {"200", "204"}
    assert "409" in paths["/v1/pipeline/runs/"]["post"]["responses"]
    assert "409" in paths["/v1/pipeline/runs/{uuid}/cancel/"]["post"]["responses"]
    assert _ref(_ok_body(schema, "/v1/pipeline/runs/")) == "PipelineRunPage"


def test_play_post_content_is_a_uuid(schema):
    content = schema["components"]["schemas"]["PlayPost"]["properties"]["content"]
    assert content["type"] == "string"
    assert content["format"] == "uuid"


def test_whole_api_generates_without_errors():
    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence():
        SchemaGenerator().get_schema(request=None, public=True)
    errors = list(GENERATOR_STATS._error_cache)
    GENERATOR_STATS.reset()
    assert errors == []
