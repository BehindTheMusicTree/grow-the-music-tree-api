from unittest.mock import patch
from uuid import uuid4

import pytest
from django.urls import reverse
from the_music_tree_genre_kit.genre_graph.models import GenreGraphDataset

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportPart import ImportPart
from grow.track.bulk_import.SongAssignmentStaging import SongAssignmentStaging
from tests.integration.track.song.test_song_import_runs import SONG, _gzip_ndjson
from tests.utils.AppTestCase import AppTestCase
from tests.utils.song_graph import install_song_graph

RUNS = reverse("song-list") + "songs/import-runs/"


class TestSemanticImportProtocol(AppTestCase):
    def setUp(self):
        super().setUp()
        genre = self.model_fixture_factory.create_genre("Graph genre")
        self.dataset = install_song_graph({genre: []})
        self.metadata = {
            "graph_revision": str(self.dataset.revision),
            "membership_revision": str(self.dataset.membership_revision),
            "expected_parts": {"songs": 1, "assignments": 1},
        }

    def test_public_camel_case_review_metadata_and_response(self):
        response = self.api_client.post(
            path=RUNS,
            data={
                "graphRevision": self.metadata["graph_revision"],
                "membershipRevision": self.metadata["membership_revision"],
                "expectedParts": self.metadata["expected_parts"],
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        assert set(response.json()) == {"runId"}
        run = BulkImportRun.objects.get(pk=response.json()["runId"])
        assert str(run.graph_revision) == self.metadata["graph_revision"]
        assert str(run.membership_revision) == self.metadata["membership_revision"]
        assert run.expected_parts == self.metadata["expected_parts"]

    def test_stale_review_does_not_abandon_existing_upload(self):
        run = self.api_client.post(path=RUNS, data=self.metadata)
        assert run.status_code == 201
        response = self.api_client.post(path=RUNS, data={**self.metadata, "membership_revision": str(uuid4())})
        assert response.status_code == 409
        assert BulkImportRun.objects.count() == 1
        assert BulkImportRun.objects.get().pk == run.data["run_id"]

    @pytest.mark.postgres
    def test_assignment_upload_receipts_completeness_reset_reupload_and_activation_guard(self):
        run_id = self.api_client.post(path=RUNS, data=self.metadata).data["run_id"]
        path = f"{RUNS}{run_id}/assignments/parts/0/"
        payload = _gzip_ndjson([{"musicbrainz_recording_id": SONG["musicbrainz_recording_id"], "assignments": {}}])
        response = self.api_client.put(path=path, data=payload, format=None, content_type="application/x-ndjson")
        assert response.status_code == 200
        assert ImportPart.objects.get(run_id=run_id, stream="assignments").row_count == 1
        commit = f"{RUNS}{run_id}/commit/"
        response = self.api_client.post(path=commit)
        assert response.status_code == 400
        assert "incomplete" in str(response.json())
        response = self.api_client.put(
            path=f"{RUNS}{run_id}/parts/0/",
            data=_gzip_ndjson([SONG]),
            format=None,
            content_type="application/x-ndjson",
        )
        assert response.status_code == 200
        SongAssignmentStaging.objects.filter(run_id=run_id).delete()
        response = self.api_client.post(path=commit)
        assert response.status_code == 400
        assert "lost or changed" in str(response.json())
        response = self.api_client.put(path=path, data=payload, format=None, content_type="application/x-ndjson")
        assert response.status_code == 200
        response = self.api_client.post(path=commit)
        assert response.status_code == 400
        assert "semantic assignment imports are required" in str(response.json())
        assert BulkImportRun.objects.get(pk=run_id).committed_on is None

    def test_invalid_part_counts_fail_before_abandonment(self):
        for parts in ({"songs": 1}, {"songs": 0, "assignments": 0}, {"songs": True, "assignments": 1}):
            response = self.api_client.post(path=RUNS, data={**self.metadata, "expected_parts": parts})
            assert response.status_code == 400
        assert not BulkImportRun.objects.exists()

    def test_out_of_range_assignment_part_fails_before_reading_body(self):
        run_id = self.api_client.post(path=RUNS, data=self.metadata).data["run_id"]
        response = self.api_client.put(
            path=f"{RUNS}{run_id}/assignments/parts/1/",
            data=b"invalid gzip",
            format=None,
            content_type="application/x-ndjson",
        )
        assert response.status_code == 400
        assert "outside" in str(response.json())

    def test_partial_or_invalid_review_metadata_preserves_existing_run(self):
        run_id = self.api_client.post(path=RUNS, data=self.metadata).data["run_id"]
        for data in (
            {"graph_revision": self.metadata["graph_revision"]},
            {key: value for key, value in self.metadata.items() if key != "graph_revision"},
            {**self.metadata, "graph_revision": None},
            {**self.metadata, "membership_revision": "not-a-uuid"},
            {**self.metadata, "expected_parts": None},
            {**self.metadata, "expected_parts": {"songs": 1, "assignments": -1}},
        ):
            response = self.api_client.post(path=RUNS, data=data)
            assert response.status_code == 400, response.data
            assert list(BulkImportRun.objects.values_list("pk", flat=True)) == [run_id]

    def test_commit_rechecks_review_tokens_before_queueing(self):
        metadata = {**self.metadata, "mode": "delta", "expected_parts": {"songs": 0, "assignments": 0, "deletions": 0}}
        for field in ("revision", "membership_revision"):
            self.dataset.refresh_from_db()
            metadata.update(
                graph_revision=str(self.dataset.revision), membership_revision=str(self.dataset.membership_revision)
            )
            run_id = self.api_client.post(path=RUNS, data=metadata).data["run_id"]
            GenreGraphDataset.objects.filter(pk=self.dataset.pk).update(**{field: uuid4()})
            with patch("grow.view.viewset.mixin.BulkImportRunMixin.enqueue_merge") as enqueue:
                response = self.api_client.post(path=f"{RUNS}{run_id}/commit/")
            assert response.status_code == 409, response.data
            enqueue.assert_not_called()
            assert BulkImportRun.objects.get(pk=run_id).committed_on is None

    @pytest.mark.postgres
    def test_delta_deletion_receipt_is_required_and_replaced(self):
        metadata = {**self.metadata, "mode": "delta", "expected_parts": {"songs": 0, "assignments": 0, "deletions": 1}}
        run_id = self.api_client.post(path=RUNS, data=metadata).data["run_id"]
        commit = f"{RUNS}{run_id}/commit/"
        response = self.api_client.post(path=commit)
        assert response.status_code == 400
        assert "incomplete" in str(response.json())
        for mbid in (uuid4(), uuid4()):
            response = self.api_client.put(
                path=f"{RUNS}{run_id}/deletions/",
                data=_gzip_ndjson([{"musicbrainz_recording_id": str(mbid)}]),
                format=None,
                content_type="application/x-ndjson",
            )
            assert response.status_code == 200, response.data
            assert list(BulkImportDeletion.objects.filter(run_id=run_id).values_list("musicbrainz_id", flat=True)) == [
                mbid
            ]
            assert ImportPart.objects.filter(run_id=run_id).count() == 1
        BulkImportDeletion.objects.filter(run_id=run_id).delete()
        response = self.api_client.post(path=commit)
        assert response.status_code == 400
        assert "lost or changed" in str(response.json())
