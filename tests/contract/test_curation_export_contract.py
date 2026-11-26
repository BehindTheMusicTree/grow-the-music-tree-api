import pytest
from django.conf import settings
from django.urls import reverse
from jsonschema.validators import validator_for
from the_music_tree_grow_contracts import SCHEMA_NAMES, first_error, load_schema
from the_music_tree_grow_contracts.curation_lists import CURATION_LISTS
from the_music_tree_grow_contracts.generate import SCHEMA_PATH, render

from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from tests.utils.AppTestCase import AppTestCase


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_published_schema_is_valid(name):
    schema = load_schema(name)

    validator_for(schema).check_schema(schema)


def test_committed_curation_export_schema_matches_the_curation_lists():
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render()


class TestCurationExportContract(AppTestCase):
    def export(self):
        self.api_client.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)
        response = self.api_client.get(reverse("curation-export"))
        assert response.status_code == 200, response.content
        return response.json()

    def test_seeded_export_then_valid(self):
        export = self.export()

        assert first_error("curation_export", export) is None
        assert export["edges"]
        assert any(export[list_name] for list_name in CURATION_LISTS)

    def test_every_relation_and_action_then_valid(self):
        for relation in ("classification", "derivation", "influence"):
            for action in ("assert", "prohibit"):
                GenreEdgeRule.objects.upsert(relation, f"Q9{relation}{action}", "Q9target", action=action, reason="r")

        export = self.export()

        assert first_error("curation_export", export) is None
        assert {(e["relation"], e["action"]) for e in export["edges"]} >= {
            (r, a) for r in ("classification", "derivation", "influence") for a in ("assert", "prohibit")
        }

    def test_row_with_an_unexpected_column_then_invalid(self):
        export = self.export()
        export["edges"][0]["extra"] = ""

        assert first_error("curation_export", export) is not None
