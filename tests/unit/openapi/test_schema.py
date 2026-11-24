import pytest
from drf_spectacular.generators import SchemaGenerator

from grow.model.history.HistoryAction import HistoryAction
from grow.openapi.views import CachedSchemaView


@pytest.fixture(scope="module")
def schema() -> dict:
    return SchemaGenerator().get_schema(request=None, public=True)


def test_history_action_enum_lists_every_action(schema):
    """Clients generate their `action` type from this enum, so it must follow the model."""
    assert schema["components"]["schemas"]["HistoryAction"]["enum"] == [a.value for a in HistoryAction]


def test_genre_history_returns_typed_entries(schema):
    ok = schema["paths"]["/v1/genres/{uuid}/history/"]["get"]["responses"]["200"]
    paginated = ok["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    items = schema["components"]["schemas"][paginated]["properties"]["results"]["items"]
    assert items["$ref"].endswith("/HistoryEntryDetailed")


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
