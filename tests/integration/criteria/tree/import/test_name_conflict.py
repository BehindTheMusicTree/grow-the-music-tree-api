from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase

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
