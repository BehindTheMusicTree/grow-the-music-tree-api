from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_graph import GraphValidationError
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphDataset
from the_music_tree_genre_kit.genre_graph.storage import GraphRevisionConflict

from grow.curation.admin_rules import upsert_admin_rule
from grow.genre_graph.models import GenreGraphImport
from grow.genre_graph.service import (
    DATASET_KEY,
    _validate_no_merged_source,
    import_reference_graph,
    restore_reference_graph,
    song_genre,
)
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase
from tests.utils.curation_export import record_export
from tests.utils.essential_songs import add_essential_song
from tests.utils.song_graph import install_song_graph, reject_scalar_genre_projection

MB_ID = "11111111-1111-4111-8111-111111111111"


class TestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
        factory = self.model_fixture_factory
        self.root = factory.create_genre("Music", wikidata_id="Q638")
        record_export(datetime(2026, 11, 14, tzinfo=UTC), [f"LOCAL:{self.root.pk}"])
        self.target = factory.create_genre("Alternative rock", wikidata_id="Q11366", parent=self.root)
        self.source = factory.create_genre("alt rock", parent=self.root)
        self.child = factory.create_genre("Child", parent=self.source)
        self.song = factory.create_song("Song", None, musicbrainz_recording_id=MB_ID)
        add_essential_song(self.source, self.song)

    def _declare_local(self, genre):
        # A merge naming a `LOCAL:` node needs it declared by an addition list, as the pipeline drops it otherwise.
        item_id = f"LOCAL:{genre.pk}"
        CurationEntry.objects.create(
            user=None,
            list_name="global_parent_additions",
            key=item_id,
            values={"item_id": item_id, "label": genre.name, "reason": "test"},
        )

    def _install(self):
        self._declare_local(self.source)
        self._declare_local(self.target)
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
        assert Song.objects.get(pk=self.song.pk).membership_genre_id == self.target.pk
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
        rule = CurationEntry.objects.get(list_name="genre_merges", user=None)
        assert {
            "decisionId": rule.values["decision_id"],
            "source": rule.values["decision_source"],
            "rationale": rule.reason,
        } == receipt.retirements[source.semantic_identity]["provenance"]

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
        self.song.refresh_from_db()
        assert self.song.membership_genre_id is None

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

    def _alias_then_receipt(self):
        before = self._install()
        mapping = {
            genre.semantic_identity: str(genre.pk)
            for genre in Genre.objects.filter(pk__in=[self.root.pk, self.target.pk, self.source.pk, self.child.pk])
        }
        # install_song_graph writes no import receipt, which a restore needs.
        GenreGraphImport.objects.create(
            revision=before.revision, mapping=mapping, curation_exported_on=before.payload["curationExportedOn"]
        )
        with reject_scalar_genre_projection():
            assert self._alias().status_code == status.HTTP_200_OK
        return before, GenreGraphDataset.objects.get(pk=DATASET_KEY).revision

    def test_restore_before_merge_while_rule_lives_then_refused(self):
        before, current = self._alias_then_receipt()

        with self.assertRaises(GraphValidationError) as raised:
            restore_reference_graph(revision=before.revision, expected_revision=current)

        assert f"LOCAL:{self.source.pk}" in str(raised.exception)
        assert GenreGraphDataset.objects.get(pk=DATASET_KEY).revision == current
        assert Genre.objects.get(pk=self.source.pk).graph_node.is_active is False

    def test_restore_before_merge_after_rule_deleted_then_source_active_again(self):
        before, current = self._alias_then_receipt()
        CurationEntry.objects.filter(list_name="genre_merges", user=None).delete()

        restore_reference_graph(revision=before.revision, expected_revision=current)

        assert Genre.objects.get(pk=self.source.pk).graph_node.is_active is True

    def test_restore_revision_produced_by_merge(self):
        _, merged = self._alias_then_receipt()
        archived = GenreGraphImport.objects.get(pk=merged)
        source_identity = f"LOCAL:{self.source.pk}"
        payload = deepcopy(GenreGraphDataset.objects.get(pk=DATASET_KEY).payload)
        edited = payload["nodes"][0]
        original_name = edited["name"]
        edited["name"] += " (updated)"
        later = import_reference_graph(
            payload=payload,
            mapping={identity: pk for identity, pk in archived.mapping.items() if identity != source_identity},
            expected_revision=merged,
            curation_exported_on=payload["curationExportedOn"],
        )

        with reject_scalar_genre_projection():
            restored = restore_reference_graph(revision=merged, expected_revision=later.revision)

        assert restored.revision != later.revision
        assert next(node["name"] for node in restored.payload["nodes"] if node["id"] == edited["id"]) == original_name
        archived.refresh_from_db()
        assert archived.mapping[source_identity] == str(self.source.pk)
        self.song.refresh_from_db()
        assert self.song.membership_genre_id == self.target.pk

        del archived.mapping[edited["id"]]
        archived.save(update_fields=["mapping"])
        with self.assertRaisesMessage(GraphValidationError, "archive is missing identity bindings"):
            restore_reference_graph(revision=merged, expected_revision=restored.revision)
        assert GenreGraphDataset.objects.get(pk=DATASET_KEY).revision == restored.revision

    def test_import_graph_naming_merged_source_then_refused(self):
        before, current = self._alias_then_receipt()
        receipt = GenreGraphImport.objects.get(pk=before.revision)

        with self.assertRaises(GraphValidationError):
            import_reference_graph(
                payload=before.payload,
                mapping=receipt.mapping,
                expected_revision=current,
                curation_exported_on=before.payload["curationExportedOn"],
            )

    def test_import_graph_without_merged_source_then_accepted(self):
        _, current = self._alias_then_receipt()
        dataset = GenreGraphDataset.objects.get(pk=DATASET_KEY)
        payload = dataset.payload
        source_identity = f"LOCAL:{self.source.pk}"
        mapping = {
            k: v for k, v in GenreGraphImport.objects.latest("created_on").mapping.items() if k != source_identity
        }

        revision = import_reference_graph(
            payload=payload,
            mapping=mapping,
            expected_revision=current,
            curation_exported_on=payload["curationExportedOn"],
        )

        applied = GenreGraphDataset.objects.get(pk=DATASET_KEY)
        assert revision.revision == applied.revision
        assert source_identity not in {node["id"] for node in applied.payload["nodes"]}
        assert Genre.objects.get(pk=self.source.pk).graph_node.is_active is False

    def _merge_rule(self, source, target):
        CurationEntry.objects.create(
            user=None,
            list_name="genre_merges",
            key=f"{source}\t{target}",
            values={
                "source_item_id": source,
                "target_item_id": target,
                "decision_id": f"{source}-{target}",
                "decision_source": "test",
                "reason": "test",
            },
        )

    def test_import_unchanged_graph_naming_merged_source_then_refused(self):
        before = self._install()
        mapping = {
            genre.semantic_identity: str(genre.pk)
            for genre in Genre.objects.filter(pk__in=[self.root.pk, self.target.pk, self.source.pk, self.child.pk])
        }
        source_identity = f"LOCAL:{self.source.pk}"
        self._merge_rule(source_identity, f"LOCAL:{self.target.pk}")

        # The payload equals the current one, so the check must come before the unchanged-graph short-circuit.
        with self.assertRaises(GraphValidationError) as raised:
            import_reference_graph(
                payload=before.payload,
                mapping=mapping,
                expected_revision=before.revision,
                curation_exported_on=before.payload["curationExportedOn"],
            )

        assert source_identity in str(raised.exception)

    def test_merge_chain_then_every_merged_source_refused(self):
        a, b, c = "LOCAL:a", "LOCAL:b", "LOCAL:c"
        self._merge_rule(a, b)
        self._merge_rule(b, c)

        for named in ({a, c}, {b, c}, {a, b, c}):
            with self.assertRaises(GraphValidationError):
                _validate_no_merged_source(SimpleNamespace(node_ids=named))
        _validate_no_merged_source(SimpleNamespace(node_ids={c}))

    def test_alias_of_target_without_identity_then_400(self):
        self._install()
        bare = self.model_fixture_factory.create_genre("Bare", parent=self.root)

        response = self._alias(target=bare)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert Genre.objects.get(pk=self.source.pk).graph_node.is_active is True
        assert not CurationEntry.objects.filter(list_name="genre_merges", user=None).exists()

    def test_alias_of_without_dataset_then_everything_moved_and_source_deleted(self):
        Song.objects.update_instance(self.song, actor=None, genre=self.source)

        response = self._alias()

        assert response.status_code == status.HTTP_200_OK, response.content
        assert not Genre.objects.filter(pk=self.source.pk).exists()
        self.child.refresh_from_db()
        assert self.child.parent.pk == self.target.pk
        assert Song.objects.get(pk=self.song.pk).genre.pk == self.target.pk
        assert [s.pk for s in self.target.essential_songs.all()] == [self.song.pk]

    def test_alias_of_merge_rule_write_fails_then_graph_rolled_back(self):
        before = self._install()
        real = upsert_admin_rule

        def failing(list_name, *args, **kwargs):
            if list_name == "genre_merges":
                raise RuntimeError("boom")
            return real(list_name, *args, **kwargs)

        with patch("grow.model.criteria.children.genre.GenreManager.upsert_admin_rule", side_effect=failing):
            response = self._alias()

        # The API's exception handler turns the error into a 500 and the request transaction rolls back.
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        assert GenreGraphDataset.objects.get(pk=DATASET_KEY).revision == before.revision
        assert Genre.objects.get(pk=self.source.pk).graph_node.is_active is True
        assert not CurationEntry.objects.filter(user=None, list_name__in=["genre_alias", "genre_merges"]).exists()
