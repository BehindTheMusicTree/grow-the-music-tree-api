from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase
from tests.integration.permission.test_google_id_token_auth import VERIFY, VIEWER_CLAIMS

CANONICAL_TREE = [
    {Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []},
    {Fields.ID: "Q1431327", Fields.NAME_PUBLIC: "Pub rock", Fields.CHILDREN: []},
    {Fields.ID: "Q187760", Fields.NAME_PUBLIC: "New wave", Fields.CHILDREN: []},
]
REGIONAL_TREE = [
    {Fields.ID: "Q16250593", Fields.NAME_PUBLIC: "Pub rock", Fields.CHILDREN: []},
    {Fields.ID: "Q1142655", Fields.NAME_PUBLIC: "new wave", Fields.CHILDREN: []},
]


class TestNameConflict(GenreTestCase):
    def _import(self, allows_multiple_primary_parents, tree):
        return self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: allows_multiple_primary_parents, Fields.TREE: tree}
        )

    def test_regional_namesake_of_canonical_genre_is_imported_flagged_and_renamable(self):
        assert self._import(False, CANONICAL_TREE).status_code == status.HTTP_201_CREATED
        assert self._import(True, REGIONAL_TREE).status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=None)
        assert genres.get(wikidata_id="Q1431327").name == "Pub rock"
        assert genres.get(wikidata_id="Q187760").name == "New wave"
        assert sorted(genres.filter(has_name_conflict=True).values_list("_name", flat=True)) == [
            "Pub rock (Q16250593)",
            "new wave (Q1142655)",
        ]

        self._list_genres(has_name_conflict="true")
        assert sorted((g["name"], g["has_name_conflict"]) for g in self.results) == [
            ("Pub rock (Q16250593)", True),
            ("new wave (Q1142655)", True),
        ]

        flagged = genres.get(wikidata_id="Q16250593")
        assert self._put_genre(flagged.uuid, data={"name": "Pub rock (Australia)"}).status_code == status.HTTP_200_OK
        assert self._import(True, REGIONAL_TREE).status_code == status.HTTP_201_CREATED

        renamed = Genre.objects.get(pk=flagged.pk)
        assert (renamed.name, renamed.has_name_conflict, renamed.is_manually_edited) == (
            "Pub rock (Australia)",
            False,
            True,
        )
        self._list_genres(has_name_conflict="true")
        assert [g["name"] for g in self.results] == ["new wave (Q1142655)"]

    def test_name_conflict_filter_is_rejected_on_tags(self):
        response = self.api_client.get(path=reverse("tag-list"), data={"has_name_conflict": "true"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestNameConflictGroups(GenreTestCase):
    def setUp(self):
        super().setUp()
        for allows_multiple_primary_parents, tree in ((False, CANONICAL_TREE), (True, REGIONAL_TREE)):
            self._post_genres_tree_import(
                data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: allows_multiple_primary_parents, Fields.TREE: tree}
            )
        self.genres = Genre.objects.filter(user=None)
        self.canonical = self.genres.get(wikidata_id="Q1431327")
        self.flagged = self.genres.get(wikidata_id="Q16250593")

    def _groups(self):
        response = self.api_client.get(path=reverse("genre-list") + "name-conflicts/")
        assert response.status_code == status.HTTP_200_OK
        return {group["name"]: [g["name"] for g in group["genres"]] for group in response.json()}

    def _validate(self, names):
        return self.api_client.post(
            path=reverse("genre-list") + "name-conflicts/validate/",
            data={"genres": [{"uuid": str(genre.uuid), "name": name} for genre, name in names]},
            handle_response=self._set_error_response_result_if_failure,
        )

    def test_groups_flagged_genres_with_their_namesakes(self):
        assert self._groups() == {
            "new wave": ["New wave", "new wave (Q1142655)"],
            "Pub rock": ["Pub rock", "Pub rock (Q16250593)"],
        }

    def test_validate_unchanged_resolves_and_locks_flagged_genre(self):
        response = self._validate([(self.canonical, "Pub rock"), (self.flagged, "Pub rock (Q16250593)")])

        assert response.status_code == status.HTTP_204_NO_CONTENT
        flagged = Genre.objects.get(pk=self.flagged.pk)
        assert (flagged.has_name_conflict, flagged.is_manually_edited) == (False, True)
        assert not Genre.objects.get(pk=self.canonical.pk).is_manually_edited
        assert list(self._groups()) == ["new wave"]

    def test_validate_renames_both_sides_and_survives_reimport(self):
        response = self._validate([(self.canonical, "Pub rock (UK)"), (self.flagged, "Pub rock (Australia)")])

        assert response.status_code == status.HTTP_204_NO_CONTENT
        self._post_genres_tree_import(data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: True, Fields.TREE: REGIONAL_TREE})
        assert Genre.objects.get(pk=self.canonical.pk).name == "Pub rock (UK)"
        flagged = Genre.objects.get(pk=self.flagged.pk)
        assert (flagged.name, flagged.has_name_conflict) == ("Pub rock (Australia)", False)
        assert list(self._groups()) == ["new wave"]

    def test_validate_clashing_name_is_rejected_on_that_genre_without_changes(self):
        response = self._validate([(self.canonical, "Pub rock (UK)"), (self.flagged, "new WAVE")])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert [e["field"] for e in self.bad_request_result_field_errors] == [str(self.flagged.uuid)]
        assert Genre.objects.get(pk=self.canonical.pk).name == "Pub rock"
        assert Genre.objects.get(pk=self.flagged.pk).has_name_conflict

    def test_validate_as_viewer_is_forbidden(self):
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            response = self._validate([(self.flagged, "Pub rock (Australia)")])

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_validate_swapping_names_within_group(self):
        response = self._validate([(self.canonical, "Pub rock (Q16250593)"), (self.flagged, "Pub rock")])

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Genre.objects.get(pk=self.canonical.pk).name == "Pub rock (Q16250593)"
        assert Genre.objects.get(pk=self.flagged.pk).name == "Pub rock"

    def test_validate_rejects_repeated_genre(self):
        response = self._validate([(self.flagged, "Pub rock (A)"), (self.flagged, "Pub rock (B)")])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=self.flagged.pk).has_name_conflict
