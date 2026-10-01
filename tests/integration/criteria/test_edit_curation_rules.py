from django.urls import reverse
from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from tests.integration.criteria.GenreTestCase import GenreTestCase

REASON = "grow admin edit by admin"


def _rows(list_name: str) -> list[dict]:
    return [entry.row for entry in CurationEntry.objects.filter(user=None, list_name=list_name, key__startswith="Q888")]


class TestCase(GenreTestCase):
    def setUp(self):
        super().setUp()
        self.rock = self.model_fixture_factory.create_genre("Rock", wikidata_id="Q888001")
        self.punk = self.model_fixture_factory.create_genre("Punk", wikidata_id="Q888002")

    def test_rename_then_label_override_and_still_locked(self):
        assert self._put_genre(self.punk.uuid, data={"name": "Punk rock"}).status_code == status.HTTP_200_OK

        assert _rows("label_overrides") == [{"item_id": "Q888002", "display_label": "Punk rock", "reason": REASON}]
        assert Genre.objects.get(pk=self.punk.pk).is_manually_edited

    def test_rename_twice_then_one_rule_with_latest_name(self):
        self._put_genre(self.punk.uuid, data={"name": "Punk rock"})
        self._put_genre(self.punk.uuid, data={"name": "Punk music"})

        assert [r["display_label"] for r in _rows("label_overrides")] == ["Punk music"]

    def test_canonical_reparent_then_main_parent(self):
        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert _rows("main_parent") == [
            {
                "item_id": "Q888002",
                "item_label": "Punk",
                "reason": REASON,
                "parent_item_id": "Q888001",
                "exclude_other_parents": True,
            }
        ]

    def test_reparent_to_root_then_400_and_rolled_back(self):
        punk = self.model_fixture_factory.create_genre("Pop punk", wikidata_id="Q888003", parent=self.rock)

        response = self._put_genre(punk.uuid, data={"name": "Pop punk", "parent": None})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=punk.pk).parent_id == self.rock.pk
        assert _rows("main_parent") == []

    def test_reparent_under_app_created_genre_then_400(self):
        local = self.model_fixture_factory.create_genre("Local genre")

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(local.uuid)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=self.punk.pk).parent_id is None

    def test_regional_reparent_then_400(self):
        region = self.model_fixture_factory.create_genre("Music of Peru", wikidata_id="Q888004", tree_name="regional")
        huayno = self.model_fixture_factory.create_genre("Huayno", wikidata_id="Q888005", tree_name="regional")

        response = self._put_genre(huayno.uuid, data={"name": "Huayno", "parent": str(region.uuid)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=huayno.pk).parent_id is None

    def test_app_created_genre_edit_then_locked_without_rule(self):
        local = self.model_fixture_factory.create_genre("Local genre")

        assert self._put_genre(local.uuid, data={"name": "Local genre 2"}).status_code == status.HTTP_200_OK

        assert Genre.objects.get(pk=local.pk).is_manually_edited
        assert not CurationEntry.objects.filter(list_name="label_overrides", values__display_label="Local genre 2")

    def test_accept_root_then_accepted_canonical_roots(self):
        Genre.objects.filter(pk=self.punk.pk).update(is_unaccepted_root=True)

        response = self.api_client.post(
            path=reverse("genre-list") + "unaccepted-roots/accept/",
            data={"genres": [{"uuid": str(self.punk.uuid)}]},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert _rows("accepted_canonical_roots") == [{"item_id": "Q888002", "item_label": "Punk"}]

    def test_exclude_then_category_list(self):
        assert self._post_genre_exclude(self.punk.uuid, "technique").status_code == status.HTTP_200_OK

        assert _rows("technique_genres") == [{"item_id": "Q888002", "item_label": "Punk", "reason": REASON}]

    def test_exclude_without_or_with_unknown_category_then_400(self):
        for category in (None, "nope"):
            response = self._post_genre_exclude(self.punk.uuid, category)

            assert response.status_code == status.HTTP_400_BAD_REQUEST, category
        assert not Genre.objects.get(pk=self.punk.pk).is_excluded

    def test_exclude_into_conflicting_list_then_400_and_rolled_back(self):
        CurationEntry.objects.upsert("theme_genres", {"item_id": "Q888002", "item_label": "Punk", "reason": "x"})

        response = self._post_genre_exclude(self.punk.uuid, "duplicate")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "theme_genres" in str(response.json())
        assert not Genre.objects.get(pk=self.punk.pk).is_excluded

    def test_synthetic_local_genre_rename_then_locked_without_rule(self):
        grouping = self.model_fixture_factory.create_genre("Dub grouping", wikidata_id="LOCAL:dub-888")

        assert self._put_genre(grouping.uuid, data={"name": "Dub"}).status_code == status.HTTP_200_OK

        assert Genre.objects.get(pk=grouping.pk).is_manually_edited
        assert not CurationEntry.objects.filter(key="LOCAL:dub-888").exists()

    def test_reparent_under_excluded_genre_then_400(self):
        Genre.objects.filter(pk=self.rock.pk).update(is_excluded=True)

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert _rows("main_parent") == []

    def test_exclude_genre_referenced_by_parent_rule_then_400(self):
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        for genre in (self.rock, self.punk):
            response = self._post_genre_exclude(genre.uuid, "theme")

            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert "main_parent" in str(response.json())
            assert not Genre.objects.get(pk=genre.pk).is_excluded

    def test_exclude_unknown_genre_then_404(self):
        response = self._post_genre_exclude("00000000-0000-0000-0000-000000000000", None)

        assert response.status_code == status.HTTP_404_NOT_FOUND
