from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.children.genre.CriteriaSource import CriteriaSource

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.integration.criteria.GenreTestCase import GenreTestCase

REASON = "grow admin edit by admin"


def _rows(list_name: str) -> list[dict]:
    return [entry.row for entry in CurationEntry.objects.filter(user=None, list_name=list_name, key__startswith="Q888")]


def _edges(relation: str | None = None) -> list[tuple]:
    """`(item_id, parent_item_id, action, exclude_other_parents)` of the test genres' edge rules."""
    rules = GenreEdgeRule.objects.filter(user=None, item_id__startswith="Q888").order_by("item_id", "parent_item_id")
    if relation:
        rules = rules.filter(relation=relation)
    return [(r.item_id, r.parent_item_id, r.action, r.exclude_other_parents) for r in rules]


class TestCase(GenreTestCase):
    def setUp(self):
        super().setUp()
        self.rock = self.model_fixture_factory.create_genre("Rock", wikidata_id="Q888001")
        self.punk = self.model_fixture_factory.create_genre("Punk", wikidata_id="Q888002")

    def test_list_by_wikidata_id_then_genre_with_its_qid(self):
        self._list_genres(wikidata_id="Q888002")

        assert [(g["name"], g["wikidataId"]) for g in self.results] == [("Punk", "Q888002")]

    def test_rename_then_label_override_and_still_locked(self):
        assert self._put_genre(self.punk.uuid, data={"name": "Punk rock"}).status_code == status.HTTP_200_OK

        assert _rows("label_overrides") == [{"item_id": "Q888002", "display_label": "Punk rock", "reason": REASON}]
        assert Genre.objects.get(pk=self.punk.pk).is_manually_edited

    def test_rename_twice_then_one_rule_with_latest_name(self):
        self._put_genre(self.punk.uuid, data={"name": "Punk rock"})
        self._put_genre(self.punk.uuid, data={"name": "Punk music"})

        assert [r["display_label"] for r in _rows("label_overrides")] == ["Punk music"]

    def test_canonical_reparent_then_canonical_parent(self):
        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert _edges("canonical_parent") == [("Q888002", "Q888001", None, True)]
        assert GenreEdgeRule.objects.get(item_id="Q888002").reason == REASON

    def test_reparent_onto_secondary_added_parent_then_add_rule_and_edge_dropped(self):
        self.punk.secondary_parents.add(self.rock)
        GenreEdgeRule.objects.upsert("secondary_parent", "Q888002", "Q888001", action="add", reason=REASON)

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert not self.punk.secondary_parents.exists()
        assert _edges("secondary_parent") == []

    def test_reparent_onto_secondary_removed_parent_then_remove_rule_replaced_by_edge(self):
        GenreEdgeRule.objects.upsert("secondary_parent", "Q888002", "Q888001", action="remove", reason=REASON)

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert _edges("secondary_parent") == []
        assert _edges("canonical_parent") == [("Q888002", "Q888001", None, True)]

    def test_reparent_without_actor_onto_secondary_added_parent_then_edge_and_rule_dropped(self):
        self.punk.secondary_parents.add(self.rock)
        GenreEdgeRule.objects.upsert("secondary_parent", "Q888002", "Q888001", action="add", reason=REASON)

        Genre.objects.update_instance(self.punk, actor=None, parent=self.rock)

        assert not self.punk.secondary_parents.exists()
        assert _edges("secondary_parent") == []

    def test_reparent_onto_additional_primary_parent_then_edge_dropped(self):
        region = self.model_fixture_factory.create_genre("Music of Peru", wikidata_id="Q888004", tree_name="regional")
        other = self.model_fixture_factory.create_genre("Music of Chile", wikidata_id="Q888006", tree_name="regional")
        huayno = self.model_fixture_factory.create_genre(
            "Huayno", wikidata_id="Q888005", tree_name="regional", parent=other
        )
        huayno.additional_primary_parents.add(region)

        Genre.objects.update_instance(huayno, actor=None, parent=region)

        assert huayno.additional_primary_parents.count() == 0
        assert Genre.objects.get(pk=huayno.pk).parent_id == region.pk

    def _make_root(self, genre):
        return self._put_genre(genre.uuid, data={"name": genre.name, "parent": None})

    def test_make_root_then_root_with_accepted_rule_and_canonical_parent_dropped(self):
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        response = self._make_root(self.punk)

        assert response.status_code == status.HTTP_200_OK
        punk = Genre.objects.get(pk=self.punk.pk)
        assert punk.parent_id is None
        assert punk.is_manually_edited
        assert not punk.is_unaccepted_root
        assert _edges("canonical_parent") == [("Q888002", None, None, True)]
        entries = HistoryEntry.objects.filter(
            action=HistoryAction.PARENT_CHANGED, content_uuid=punk.uuid, new_value=None
        )
        assert [(e.old_value, e.actor_id is not None) for e in entries] == [("Rock", True)]

    def test_make_root_clears_unaccepted_root_flag(self):
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})
        Genre.objects.filter(pk=self.punk.pk).update(is_unaccepted_root=True)

        assert self._make_root(self.punk).status_code == status.HTTP_200_OK

        assert not Genre.objects.get(pk=self.punk.pk).is_unaccepted_root

    def test_make_root_then_reparent_then_accepted_rule_dropped(self):
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})
        self._make_root(self.punk)

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert _edges("canonical_parent") == [("Q888002", "Q888001", None, True)]

    def test_reparent_accepted_root_then_accepted_rule_dropped(self):
        GenreEdgeRule.objects.upsert("canonical_parent", "Q888002", None, exclude_other_parents=True)

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert _edges("canonical_parent") == [("Q888002", "Q888001", None, True)]

    def test_make_root_of_app_created_genre_then_root_without_rule(self):
        local = self.model_fixture_factory.create_genre("Local genre", parent=self.rock)

        rules_before = GenreEdgeRule.objects.filter(parent_item_id=None).count()

        assert self._make_root(local).status_code == status.HTTP_200_OK

        assert Genre.objects.get(pk=local.pk).parent_id is None
        assert GenreEdgeRule.objects.filter(parent_item_id=None).count() == rules_before

    def test_make_root_of_root_then_noop_without_rule(self):
        response = self._make_root(self.rock)

        assert response.status_code == status.HTTP_200_OK
        assert _edges("canonical_parent") == []

    def test_make_root_of_regional_genre_then_400_and_rolled_back(self):
        region = self.model_fixture_factory.create_genre("Music of Peru", wikidata_id="Q888004", tree_name="regional")
        huayno = self.model_fixture_factory.create_genre(
            "Huayno", wikidata_id="Q888005", tree_name="regional", parent=region
        )

        response = self._make_root(huayno)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=huayno.pk).parent_id == region.pk

    def test_make_root_of_excluded_genre_then_400(self):
        punk = self.model_fixture_factory.create_genre("Pop punk", wikidata_id="Q888003", parent=self.rock)
        Genre.objects.filter(pk=punk.pk).update(is_excluded=True)

        response = self._make_root(punk)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=punk.pk).parent_id == self.rock.pk

    def _adopted(self, name: str) -> Genre:
        return Genre.objects.get(name=name)

    def _additions(self) -> dict[str, str]:
        entries = CurationEntry.objects.filter(
            user=None, list_name="canonical_parent_additions", key__startswith="LOCAL:"
        )
        return {e.key: e.row["label"] for e in entries}

    def _local_edges(self) -> list[tuple]:
        rules = GenreEdgeRule.objects.filter(user=None).order_by("item_id", "parent_item_id")
        return [(r.item_id, r.parent_item_id) for r in rules if r.item_id.startswith(("Q888", "LOCAL:"))]

    def test_reparent_under_app_created_genre_then_parent_adopted_as_local_node(self):
        local = self.model_fixture_factory.create_genre("Local genre")

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(local.uuid)})

        assert response.status_code == status.HTTP_200_OK
        local = Genre.objects.get(pk=local.pk)
        assert local.wikidata_id == "LOCAL:local-genre"
        assert local.source == CriteriaSource.APP
        assert local.is_manually_edited
        assert self._additions() == {"LOCAL:local-genre": "Local genre"}
        assert self._local_edges() == [("LOCAL:local-genre", None), ("Q888002", "LOCAL:local-genre")]
        assert GenreEdgeRule.objects.get(item_id="Q888002").exclude_other_parents
        assert HistoryEntry.objects.filter(
            content_uuid=local.pk, action=HistoryAction.UPDATED, new_value__startswith="adopted"
        ).exists()
        assert HistoryEntry.objects.filter(content_uuid=self.punk.pk, action=HistoryAction.PARENT_CHANGED).exists()

    def test_reparent_under_nested_app_created_genres_then_whole_chain_adopted(self):
        outer = self.model_fixture_factory.create_genre("Outer", parent=self.rock)
        inner = self.model_fixture_factory.create_genre("Inner", parent=outer)

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(inner.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert self._additions() == {"LOCAL:inner": "Inner", "LOCAL:outer": "Outer"}
        assert self._local_edges() == [
            ("LOCAL:inner", "LOCAL:outer"),
            ("LOCAL:outer", "Q888001"),
            ("Q888002", "LOCAL:inner"),
        ]

    def test_reparent_under_app_created_genres_with_same_slug_then_ids_suffixed(self):
        first = self.model_fixture_factory.create_genre("Fusion")
        second = self.model_fixture_factory.create_genre("fusion!")
        other = self.model_fixture_factory.create_genre("Jazz", wikidata_id="Q888006")

        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(first.uuid)})
        self._put_genre(other.uuid, data={"name": "Jazz", "parent": str(second.uuid)})

        assert Genre.objects.get(pk=first.pk).wikidata_id == "LOCAL:fusion"
        assert Genre.objects.get(pk=second.pk).wikidata_id == "LOCAL:fusion-2"

    def test_reparent_under_second_child_of_adopted_genre_then_reuses_id(self):
        local = self.model_fixture_factory.create_genre("Local genre")
        other = self.model_fixture_factory.create_genre("Jazz", wikidata_id="Q888006")

        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(local.uuid)})
        self._put_genre(other.uuid, data={"name": "Jazz", "parent": str(local.uuid)})

        assert list(self._additions()) == ["LOCAL:local-genre"]

    def test_reparent_under_excluded_app_created_genre_then_400_and_nothing_adopted(self):
        local = self.model_fixture_factory.create_genre("Local genre")
        Genre.objects.filter(pk=local.pk).update(is_excluded=True)

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(local.uuid)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=local.pk).wikidata_id is None
        assert self._additions() == {}

    def test_reparent_under_regional_app_created_genre_then_400(self):
        local = self.model_fixture_factory.create_genre("Local region", tree_name="regional")

        response = self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(local.uuid)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=local.pk).wikidata_id is None

    def test_rename_adopted_genre_then_addition_label_updated_and_id_kept(self):
        local = self.model_fixture_factory.create_genre("Local genre")
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(local.uuid)})

        assert self._put_genre(local.uuid, data={"name": "Renamed"}).status_code == status.HTTP_200_OK

        assert Genre.objects.get(pk=local.pk).wikidata_id == "LOCAL:local-genre"
        assert self._additions() == {"LOCAL:local-genre": "Renamed"}

    def test_delete_adopted_genre_then_children_edges_repointed_and_addition_dropped(self):
        outer = self.model_fixture_factory.create_genre("Outer", parent=self.rock)
        inner = self.model_fixture_factory.create_genre("Inner", parent=outer)
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(inner.uuid)})

        Genre.objects.delete_instance(Genre.objects.get(pk=inner.pk), actor=self.admin)

        assert self._additions() == {"LOCAL:outer": "Outer"}
        assert self._local_edges() == [("LOCAL:outer", "Q888001"), ("Q888002", "LOCAL:outer")]

    def test_delete_adopted_root_genre_then_children_become_accepted_roots(self):
        local = self.model_fixture_factory.create_genre("Local genre")
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(local.uuid)})

        Genre.objects.delete_instance(Genre.objects.get(pk=local.pk), actor=self.admin)

        assert self._additions() == {}
        assert self._local_edges() == [("Q888002", None)]

    def test_export_after_adoption_then_200_and_dangling_local_edge_then_409(self):
        local = self.model_fixture_factory.create_genre("Local genre")
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(local.uuid)})

        assert self.api_client.get(path=reverse("curation-export")).status_code == status.HTTP_200_OK

        GenreEdgeRule.objects.filter(item_id="Q888002").update(parent_item_id="LOCAL:ghost")
        assert self.api_client.get(path=reverse("curation-export")).status_code == status.HTTP_409_CONFLICT

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
        assert _edges("canonical_parent") == [("Q888002", None, None, True)]

    def test_exclude_then_category_list(self):
        assert self._post_genre_exclude(self.punk.uuid, "technique").status_code == status.HTTP_200_OK

        assert _rows("technique_genres") == [{"item_id": "Q888002", "reason": REASON}]

    def test_exclude_without_or_with_unknown_category_then_400(self):
        for category in (None, "nope"):
            response = self._post_genre_exclude(self.punk.uuid, category)

            assert response.status_code == status.HTTP_400_BAD_REQUEST, category
        assert not Genre.objects.get(pk=self.punk.pk).is_excluded

    def test_exclude_into_conflicting_list_then_400_and_rolled_back(self):
        CurationEntry.objects.upsert("theme_genres", {"item_id": "Q888002", "reason": "x"})

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
        assert _edges("canonical_parent") == []

    def test_exclude_genre_referenced_by_parent_rule_then_400(self):
        self._put_genre(self.punk.uuid, data={"name": "Punk", "parent": str(self.rock.uuid)})

        for genre in (self.rock, self.punk):
            response = self._post_genre_exclude(genre.uuid, "theme")

            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert "canonical_parent" in str(response.json())
            assert not Genre.objects.get(pk=genre.pk).is_excluded

    def test_exclude_unknown_genre_then_404(self):
        response = self._post_genre_exclude("00000000-0000-0000-0000-000000000000", None)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_side_to_pop_then_pop_side_rule_locked_and_history(self):
        pop_punk = self.model_fixture_factory.create_genre("Pop punk", wikidata_id="Q888003", parent=self.rock)

        response = self._put_genre(pop_punk.uuid, data={"name": "Pop punk", "side": "pop"})

        assert response.status_code == status.HTTP_200_OK
        assert _rows("canonical_genre_pop_side") == [
            {"root_item_id": "Q888001", "pop_child_item_id": "Q888003", "reason": REASON}
        ]
        genre = Genre.objects.get(pk=pop_punk.pk)
        assert genre.side == "pop"
        assert genre.is_manually_edited
        history = HistoryEntry.objects.filter(action=HistoryAction.SIDE_CHANGED).get()
        assert (history.old_value, history.new_value) == ("core", "pop")

    def test_side_back_to_core_then_pop_side_rule_deleted(self):
        pop_punk = self.model_fixture_factory.create_genre("Pop punk", wikidata_id="Q888003", parent=self.rock)
        self._put_genre(pop_punk.uuid, data={"name": "Pop punk", "side": "pop"})

        response = self._put_genre(pop_punk.uuid, data={"name": "Pop punk", "side": "core"})

        assert response.status_code == status.HTTP_200_OK
        assert _rows("canonical_genre_pop_side") == []
        assert Genre.objects.get(pk=pop_punk.pk).side == "core"

    def test_side_to_pop_on_local_grouping_then_rule_with_local_ids(self):
        grouping = self.model_fixture_factory.create_genre("Rock grouping", wikidata_id="LOCAL:rock-888")
        pop = self.model_fixture_factory.create_genre("Pop rock", wikidata_id="LOCAL:pop-rock-888", parent=grouping)

        assert self._put_genre(pop.uuid, data={"name": "Pop rock", "side": "pop"}).status_code == status.HTTP_200_OK

        assert CurationEntry.objects.filter(
            list_name="canonical_genre_pop_side", key="LOCAL:rock-888\tLOCAL:pop-rock-888"
        ).exists()

    def test_second_pop_child_then_400_and_rolled_back(self):
        pop_punk = self.model_fixture_factory.create_genre("Pop punk", wikidata_id="Q888003", parent=self.rock)
        soft_rock = self.model_fixture_factory.create_genre("Soft rock", wikidata_id="Q888004", parent=self.rock)
        self._put_genre(pop_punk.uuid, data={"name": "Pop punk", "side": "pop"})

        response = self._put_genre(soft_rock.uuid, data={"name": "Soft rock", "side": "pop"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=soft_rock.pk).side != "pop"
        assert [r["pop_child_item_id"] for r in _rows("canonical_genre_pop_side")] == ["Q888003"]

    def test_side_to_pop_off_root_child_then_400(self):
        pop_punk = self.model_fixture_factory.create_genre("Pop punk", wikidata_id="Q888003", parent=self.rock)
        skate_punk = self.model_fixture_factory.create_genre("Skate punk", wikidata_id="Q888004", parent=pop_punk)

        response = self._put_genre(skate_punk.uuid, data={"name": "Skate punk", "side": "pop"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert _rows("canonical_genre_pop_side") == []

    def test_side_to_pop_under_mainstream_pop_root_then_400(self):
        mainstream = self.model_fixture_factory.create_genre("Mainstream Pop", wikidata_id="Q888010")
        teen_pop = self.model_fixture_factory.create_genre("Teen pop", wikidata_id="Q888011", parent=mainstream)

        response = self._put_genre(teen_pop.uuid, data={"name": "Teen pop", "side": "pop"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "side" in str(response.json())
        assert Genre.objects.get(pk=teen_pop.pk).side != "pop"
        assert _rows("canonical_genre_pop_side") == []

    def test_side_to_pop_on_app_created_genre_then_locked_without_rule(self):
        mine = self.model_fixture_factory.create_genre("My pop", parent=self.rock)

        assert self._put_genre(mine.uuid, data={"name": "My pop", "side": "pop"}).status_code == status.HTTP_200_OK

        assert Genre.objects.get(pk=mine.pk).is_manually_edited
        assert _rows("canonical_genre_pop_side") == []
