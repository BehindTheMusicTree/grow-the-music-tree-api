from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestOverwrite(GenreTestCase):
    def test_import_new_tree_keeps_existing_genre_without_wikidata_id(self):
        self.model_fixture_factory.create_genre(name="Old Rock")

        tree_data = [
            {Fields.NAME_PUBLIC: "New Rock", Fields.CHILDREN: []},
            {Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []},
        ]
        response = self._post_genres_tree_import(data={Fields.TREE: tree_data})

        assert response.status_code == status.HTTP_201_CREATED

        # "Old Rock" has no wikidataId, so import_criteria_tree never touches it (merge-by-wikidataId).
        genres = Genre.objects.filter(user=self.system_user)
        assert genres.count() == 3
        assert genres.get(name="New Rock") is not None
        assert genres.get(name="Old Rock") is not None

    def test_import_matches_existing_genre_by_wikidata_id_and_updates_in_place(self):
        existing = self.model_fixture_factory.create_genre(name="Rock", wikidata_id="Q11399")

        tree_data = [
            {Fields.ID: "Q11399", Fields.NAME_PUBLIC: "Rock Music", Fields.CHILDREN: []},
            {Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []},
        ]
        response = self._post_genres_tree_import(data={Fields.TREE: tree_data})

        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=self.system_user)
        assert genres.count() == 2
        updated = genres.get(wikidata_id="Q11399")
        assert updated.pk == existing.pk
        assert updated.name == "Rock Music"

    def test_import_deletes_existing_genre_whose_wikidata_id_is_no_longer_in_tree(self):
        self.model_fixture_factory.create_genre(name="Disco", wikidata_id="Q182985")

        tree_data = [
            {Fields.ID: "Q11399", Fields.NAME_PUBLIC: "Rock", Fields.CHILDREN: []},
            {Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []},
        ]
        response = self._post_genres_tree_import(data={Fields.TREE: tree_data})

        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=self.system_user)
        assert not genres.filter(wikidata_id="Q182985").exists()
        assert genres.get(wikidata_id="Q11399").name == "Rock"

    def test_import_reparents_track_off_a_genre_deleted_by_the_reimport(self):
        # Track.genre is on_delete=DO_NOTHING; a raw bulk delete of a genre still referenced by a
        # track would violate the FK constraint. the-music-tree-genre-kit reparents the track
        # instead (up to the deleted genre's parent, or null for a deleted root) rather than
        # raising or deleting the track.
        disco = self.model_fixture_factory.create_genre(name="Disco", wikidata_id="Q182985")
        track = self.model_fixture_factory.create_youtube_track(title="Le Freak", genre=disco)

        tree_data = [
            {Fields.ID: "Q11399", Fields.NAME_PUBLIC: "Rock", Fields.CHILDREN: []},
            {Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []},
        ]
        response = self._post_genres_tree_import(data={Fields.TREE: tree_data})

        assert response.status_code == status.HTTP_201_CREATED
        assert not Genre.objects.filter(user=self.system_user, wikidata_id="Q182985").exists()
        track.refresh_from_db()
        assert track.genre_id is None
