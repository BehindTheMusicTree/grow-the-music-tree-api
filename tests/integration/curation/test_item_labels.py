from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from grow.curation.labels import resolve_item_labels
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.WikidataItem import WikidataItem
from tests.utils.AppTestCase import AppTestCase

PRUNED, TREE, ADDED = "Q999999990", "Q999999991", "LOCAL:test-node"


def _entry(list_name: str, key: str, **values) -> CurationEntry:
    return CurationEntry.objects.create(user=None, list_name=list_name, key=key, values=values, reason="r")


class TestItemLabels(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

    def _push(self, items: list[dict]):
        return self.pipeline.post(path=reverse("curation-wikidata-items"), data={"items": items}, format="json")

    def test_resolve_then_tree_over_catalog_over_pending_addition(self):
        self.model_fixture_factory.create_genre("Rock", wikidata_id=TREE)
        WikidataItem.objects.bulk_create(
            [WikidataItem(item_id=TREE, label="Rock music"), WikidataItem(item_id=PRUNED, label="Cosplay")]
        )
        _entry("canonical_parent_additions", ADDED, label="Test node")
        _entry("canonical_parent_additions", TREE, label="Stale")

        labels = resolve_item_labels({TREE, PRUNED, ADDED, "Q1"})

        assert labels == {TREE: "Rock", PRUNED: "Cosplay", ADDED: "Test node"}

    def test_push_catalog_then_replaces_previous(self):
        self._push([{"id": PRUNED, "label": "Cosplay"}, {"id": TREE, "label": "Rock"}])

        response = self._push([{"id": TREE, "label": "Rock music"}])

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"itemCount": 1}
        assert dict(WikidataItem.objects.values_list("item_id", "label")) == {TREE: "Rock music"}

    def test_push_catalog_with_bad_id_then_400_and_catalog_kept(self):
        WikidataItem.objects.create(item_id=TREE, label="Rock")

        response = self._push([{"id": "not-a-qid", "label": "x"}])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert WikidataItem.objects.count() == 1

    def test_push_catalog_as_anonymous_then_401(self):
        response = APIClient().post(path=reverse("curation-wikidata-items"), data={"items": []}, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_entry_of_pruned_item_then_labelled_from_catalog(self):
        WikidataItem.objects.create(item_id=PRUNED, label="Cosplay")
        created = self.api_client.post(
            path=reverse("curation-entries", kwargs={"list_name": "theme_genres"}),
            data={"row": {"item_id": PRUNED, "reason": "r"}},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.content

        response = self.api_client.get(
            path=reverse("curation-entries", kwargs={"list_name": "theme_genres"}), data={"q": PRUNED}
        )

        assert response.json()["labels"] == {PRUNED: "Cosplay"}

    def test_history_then_labels_of_snapshot_item_ids(self):
        WikidataItem.objects.create(item_id=PRUNED, label="Cosplay")
        created = self.api_client.post(
            path=reverse("curation-entries", kwargs={"list_name": "theme_genres"}),
            data={"row": {"item_id": PRUNED, "reason": "r"}},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.content

        response = self.api_client.get(path=reverse("curation-history"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["labels"] == {PRUNED: "Cosplay"}

    def test_search_then_items_from_tree_catalog_and_additions_by_name_or_id(self):
        self.model_fixture_factory.create_genre("Zyx", wikidata_id=TREE)
        WikidataItem.objects.create(item_id=PRUNED, label="Zyx cosplay")
        _entry("canonical_parent_additions", ADDED, label="Zyx steady")

        by_name = self.api_client.get(path=reverse("curation-items"), data={"q": "zyx"})
        by_id = self.api_client.get(path=reverse("curation-items"), data={"q": PRUNED.lower()})

        assert by_name.status_code == status.HTTP_200_OK
        assert by_name.json()["results"] == [
            {"id": TREE, "label": "Zyx"},
            {"id": PRUNED, "label": "Zyx cosplay"},
            {"id": ADDED, "label": "Zyx steady"},
        ]
        assert by_id.json()["results"] == [{"id": PRUNED, "label": "Zyx cosplay"}]

    def test_search_without_query_then_400(self):
        response = self.api_client.get(path=reverse("curation-items"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_lists_then_column_specs(self):
        response = self.api_client.get(path=reverse("curation-lists"))

        specs = {lst["name"]: lst["columnSpecs"] for lst in response.json()}
        assert specs["main_parent"] == [
            {"name": "item_id", "kind": "item_id", "optional": False},
            {"name": "reason", "kind": "text", "optional": False},
            {"name": "parent_item_id", "kind": "item_id", "optional": False},
            {"name": "exclude_other_parents", "kind": "bool", "optional": False},
        ]
        assert {"name": "label", "kind": "text", "optional": False} in specs["canonical_parent_additions"]
        assert {"name": "genre_item_id", "kind": "item_id", "optional": True} in specs["song_genre"]
