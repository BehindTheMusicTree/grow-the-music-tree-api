from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphDataset
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict

from grow.genre_graph.models import GenreGraphImport
from grow.genre_graph.service import DATASET_KEY, restore_reference_graph, song_genre
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase
from tests.utils.essential_songs import add_essential_song
from tests.utils.song_graph import install_song_graph

MB_ID = "11111111-1111-4111-8111-111111111111"


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        CurationSyncState.objects.update_or_create(pk=1, defaults={"exported_on": datetime(2026, 11, 14, tzinfo=UTC)})
        GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
        factory = self.model_fixture_factory
        self.root = factory.create_genre("Music", wikidata_id="Q638")
        self.target = factory.create_genre("Alternative rock", wikidata_id="Q11366", parent=self.root)
        self.source = factory.create_genre("alt rock", parent=self.root)
        self.child = factory.create_genre("Child", parent=self.source)
        self.song = factory.create_song("Song", None, musicbrainz_recording_id=MB_ID)
        add_essential_song(self.source, self.song)

    def _install(self):
        return install_song_graph(
            {self.root: [], self.target: [], self.source: [self.song], self.child: []},
            classifications=[(self.target, self.root), (self.source, self.root), (self.child, self.source)],
            node_overrides={
                self.target: {"displayParentId": f"LOCAL:{self.root.pk}"},
                self.source: {"displayParentId": f"LOCAL:{self.root.pk}"},
                self.child: {"displayParentId": f"LOCAL:{self.source.pk}"},
            },
        )

    def _alias(self, source=None, target=None):
        return self.api_client.post(
            reverse("genre-alias-of", kwargs={"pk": (source or self.source).uuid}),
            {"target": str((target or self.target).uuid)},
            format="json",
        )

    def test_alias_of_then_node_retired_and_everything_moved(self):
        before = self._install()
        token = GenreTreeVersion.objects.get(pk=1).token

        response = self._alias()

        assert response.status_code == status.HTTP_200_OK, response.content
        source = Genre.objects.get(pk=self.source.pk)
        assert source.graph_node.is_active is False
        assert song_genre(Song.objects.get(pk=self.song.pk)) == self.target
        assert GenreGraphAttribution.objects.filter(node=source.graph_node).count() == 0
        self.child.refresh_from_db()
        assert self.child.parent.pk == self.target.pk
        assert [s.pk for s in self.target.essential_songs.all()] == [self.song.pk]
        assert CurationEntry.objects.filter(list_name="genre_alias", user=None).count() == 1
        assert CurationEntry.objects.filter(list_name="genre_merges", user=None).count() == 1
        dataset = GenreGraphDataset.objects.get(pk=DATASET_KEY)
        assert dataset.revision != before.revision
        receipt = GenreGraphImport.objects.get(pk=dataset.revision)
        assert receipt.mapping[source.semantic_identity] == str(self.source.pk)
        self.target.refresh_from_db()
        assert receipt.retirements[source.semantic_identity]["target"] == self.target.semantic_identity
        assert GenreTreeVersion.objects.get(pk=1).token != token

    def test_alias_of_then_counts_follow_source_attributions(self):
        self._install()

        response = self.api_client.get(
            reverse("genre-alias-of-preview", kwargs={"pk": self.source.uuid}), {"target": str(self.target.uuid)}
        )

        assert response.json() == {"songs": 1, "essentialSongs": 1, "children": 1}

    def test_alias_of_other_kind_then_400_and_no_write(self):
        install_song_graph(
            {self.root: [], self.target: [], self.source: [], self.child: []},
            classifications=[(self.target, self.root), (self.child, self.root)],
            node_overrides={self.source: {"kind": "overview"}},
        )
        revision = GenreGraphDataset.objects.get(pk=DATASET_KEY).revision

        response = self._alias()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "different kinds" in response.json()["detail"]
        assert GenreGraphDataset.objects.get(pk=DATASET_KEY).revision == revision
        assert Genre.objects.get(pk=self.source.pk).graph_node.is_active is True

    def test_alias_of_into_regional_target_then_400_and_no_write(self):
        overview = self.model_fixture_factory.create_genre("Region")
        install_song_graph(
            {self.root: [], self.target: [], self.source: [self.song], self.child: [], overview: []},
            classifications=[(self.source, self.root), (self.child, self.source)],
            node_overrides={overview: {"kind": "overview"}},
            regional={self.target: overview},
        )
        revision = GenreGraphDataset.objects.get(pk=DATASET_KEY).revision

        response = self._alias()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "paths" in response.json()
        assert GenreGraphDataset.objects.get(pk=DATASET_KEY).revision == revision

    def test_alias_of_stale_revision_then_409(self):
        self._install()
        with patch("grow.genre_graph.service.merge_graph_nodes", side_effect=GraphRevisionConflict("stale")):
            response = self._alias()

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_restore_previous_revision_then_source_active_again(self):
        before = self._install()
        mapping = {
            genre.semantic_identity: str(genre.pk)
            for genre in Genre.objects.filter(pk__in=[self.root.pk, self.target.pk, self.source.pk, self.child.pk])
        }
        # install_song_graph writes no import receipt, which a restore needs.
        GenreGraphImport.objects.create(
            revision=before.revision, mapping=mapping, curation_exported_on=before.payload["curationExportedOn"]
        )
        assert self._alias().status_code == status.HTTP_200_OK
        current = GenreGraphDataset.objects.get(pk=DATASET_KEY).revision

        restore_reference_graph(revision=before.revision, expected_revision=current)

        assert Genre.objects.get(pk=self.source.pk).graph_node.is_active is True
