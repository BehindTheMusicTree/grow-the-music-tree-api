from unittest.mock import patch
from uuid import uuid4

from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.history.HistoryAction import HistoryAction
from grow.model.history.HistoryEntry import HistoryEntry
from tests.integration.criteria.GenreTestCase import GenreTestCase
from tests.integration.permission.test_google_id_token_auth import VERIFY, VIEWER_CLAIMS

PALA = {Fields.ID: "Q15724583", Fields.NAME_PUBLIC: "Pala", Fields.IS_UNACCEPTED_ROOT: True, Fields.CHILDREN: []}
MAINSTREAM_POP = {Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}
TREE = [MAINSTREAM_POP, PALA]
PARENTED_TREE = [{**MAINSTREAM_POP, Fields.CHILDREN: [{**PALA, Fields.IS_UNACCEPTED_ROOT: False}]}]


class TestUnacceptedRoot(GenreTestCase):
    def setUp(self):
        super().setUp()
        self._import(TREE)
        self.pala = Genre.objects.get(user=None, wikidata_id="Q15724583")

    def _import(self, tree):
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: tree}
        )
        assert response.status_code == status.HTTP_201_CREATED

    def _unaccepted_roots(self):
        response = self.api_client.get(path=reverse("genre-list") + "unaccepted-roots/")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def _accept(self, uuids):
        return self.api_client.post(
            path=reverse("genre-list") + "unaccepted-roots/accept/",
            data={"genres": [{"uuid": str(uuid)} for uuid in uuids]},
            handle_response=self._set_error_response_result_if_failure,
        )

    def test_import_flags_node_and_lists_it(self):
        assert self.pala.is_unaccepted_root
        assert not Genre.objects.get(user=None, wikidata_id="Q373342").is_unaccepted_root

        [genre] = self._unaccepted_roots()
        assert (genre["uuid"], genre["name"], genre["wikidataId"], genre["isUnacceptedRoot"]) == (
            str(self.pala.uuid),
            "Pala",
            "Q15724583",
            True,
        )

        self._list_genres(is_unaccepted_root="true")
        assert [g["name"] for g in self.results] == ["Pala"]

    def test_accept_unflags_locks_and_records_history(self):
        assert self._accept([self.pala.uuid]).status_code == status.HTTP_204_NO_CONTENT

        pala = Genre.objects.get(pk=self.pala.pk)
        assert (pala.is_unaccepted_root, pala.is_manually_edited) == (False, True)
        assert HistoryEntry.objects.filter(content_uuid=pala.uuid, action=HistoryAction.ROOT_ACCEPTED).exists()
        assert self._unaccepted_roots() == []

    def test_acceptance_survives_reimport(self):
        self._accept([self.pala.uuid])
        self._import(TREE)

        assert not Genre.objects.get(pk=self.pala.pk).is_unaccepted_root

    def test_reimport_with_parent_clears_flag(self):
        self._import(PARENTED_TREE)

        pala = Genre.objects.get(pk=self.pala.pk)
        assert pala.parent.name == "Mainstream Pop"
        assert not pala.is_unaccepted_root

    def test_admin_reparent_clears_flag(self):
        parent = Genre.objects.get(user=None, wikidata_id="Q373342")

        response = self._put_genre(self.pala.uuid, data={"parent": str(parent.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert not Genre.objects.get(pk=self.pala.pk).is_unaccepted_root
        assert self._unaccepted_roots() == []

    def test_accept_as_viewer_is_forbidden(self):
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            response = self._accept([self.pala.uuid])

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_accept_unflagged_uuid_is_rejected_on_that_uuid(self):
        mainstream_pop = Genre.objects.get(user=None, wikidata_id="Q373342")

        response = self._accept([self.pala.uuid, mainstream_pop.uuid])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert [e["field"] for e in self.bad_request_result_field_errors] == [str(mainstream_pop.uuid)]
        assert Genre.objects.get(pk=self.pala.pk).is_unaccepted_root

    def test_accept_unknown_uuid_is_rejected_on_that_uuid(self):
        unknown = uuid4()

        response = self._accept([unknown])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert [e["field"] for e in self.bad_request_result_field_errors] == [str(unknown)]

    def test_accept_rejects_repeated_genre(self):
        response = self._accept([self.pala.uuid, self.pala.uuid])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Genre.objects.get(pk=self.pala.pk).is_unaccepted_root
