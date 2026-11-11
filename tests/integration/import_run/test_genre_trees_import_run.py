from unittest.mock import patch

import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.ImportAttempt import ImportAttempt
from grow.genre_music.catalogue_verification import verify_catalogue_counts
from grow.genre_tree.bulk_import.GenreTreeImportPayload import GenreTreeImportPayload
from grow.model.criteria.children.genre.Genre import Genre
from grow.model.import_run.ImportRun import ImportRun
from tests.utils.AppTestCase import AppTestCase
from tests.utils.curation_export import export_curation

POP = {Fields.ID: "Q373342", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}
ROCK = {Fields.ID: "Q11399", Fields.NAME_PUBLIC: "Rock", Fields.CHILDREN: []}
FOLK = {Fields.ID: "Q1342372", Fields.NAME_PUBLIC: "Breton folk", Fields.CHILDREN: []}
BRITTANY = {Fields.ID: "Q1059", Fields.NAME_PUBLIC: "Music of Brittany", Fields.CHILDREN: [FOLK]}


class TestGenreTreesImportRun(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)
        self.url = reverse("genre-list") + "trees/import-runs/"

    def _body(self, trees, exported_on=None):
        """A batch of Gold tree files: the pipeline's files each carry the curation export they were built from."""
        extra = {"curationExportedOn": exported_on} if exported_on else {}
        return {"trees": [{"treeName": name, "tree": tree, **extra} for name, tree in trees]}

    def _status(self, client, task_id):
        return client.get(reverse("genre-list") + f"trees/import/{task_id}/status/")

    def _import(self, trees):
        response = self.api_client.post(self.url, data=self._body(trees), format="json")
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert self._status(self.api_client, response.json()["taskId"]).json()["status"] == "success"

    def test_genre_deleted_by_the_run_then_song_reparented_with_consistent_counts(self):
        self._import([("canonical", [POP, ROCK]), ("regional", [BRITTANY])])
        folk = Genre.objects.get(wikidata_id="Q1342372")
        song = self.model_fixture_factory.create_song(title="Gwerz", genre=folk)

        self._import([("canonical", [POP, ROCK]), ("regional", [{**BRITTANY, Fields.CHILDREN: []}])])

        assert not Genre.objects.filter(wikidata_id="Q1342372").exists()
        song.refresh_from_db()
        assert song.genre_id == Genre.objects.get(wikidata_id="Q1059").pk
        assert all(report.valid for report in verify_catalogue_counts().values())

    def test_pipeline_run_then_both_trees_imported_and_recorded(self):
        body = self._body(
            [("canonical", [POP, ROCK]), ("regional", [BRITTANY])], exported_on=export_curation(self.pipeline)
        )

        response = self.pipeline.post(self.url, data=body, format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED
        polled = self._status(self.pipeline, response.json()["taskId"]).json()
        assert polled["status"] == "success"
        assert set(Genre.objects.values_list("wikidata_id", flat=True)) >= {"Q373342", "Q11399", "Q1059", "Q1342372"}
        assert list(ImportRun.objects.order_by("pk").values_list("kind", "count")) == [
            ("canonical_tree", 2),
            ("regional_tree", 2),
        ]
        assert not GenreTreeImportPayload.objects.exists()

    def test_admin_run_then_not_recorded(self):
        response = self.api_client.post(self.url, data=self._body([("canonical", [POP, ROCK])]), format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert self._status(self.api_client, response.json()["taskId"]).json()["status"] == "success"
        assert not ImportRun.objects.exists()

    def test_pipeline_run_without_curation_export_then_400(self):
        response = self.pipeline.post(self.url, data=self._body([("canonical", [POP, ROCK])]), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not BulkImportRun.objects.exists()

    def test_pipeline_run_with_mixed_curation_exports_then_400(self):
        exported_on = export_curation(self.pipeline)
        body = self._body([("canonical", [POP, ROCK]), ("regional", [BRITTANY])], exported_on=exported_on)
        body["trees"][1]["curationExportedOn"] = "2000-01-01T00:00:00Z"

        response = self.pipeline.post(self.url, data=body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "trees" in response.json()["details"]["fieldErrors"]
        assert not BulkImportRun.objects.exists()

    def test_top_level_key_other_than_trees_then_400(self):
        body = {**self._body([("canonical", [POP, ROCK])]), "curationExportedOn": export_curation(self.pipeline)}

        response = self.pipeline.post(self.url, data=body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "curationExportedOn" in response.json()["details"]["fieldErrors"]
        assert not BulkImportRun.objects.exists()

    def test_admin_run_with_per_tree_curation_export_then_400(self):
        body = self._body([("canonical", [POP, ROCK])], exported_on="2026-01-01T00:00:00Z")

        response = self.api_client.post(self.url, data=body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not BulkImportRun.objects.exists()

    def test_empty_trees_then_400(self):
        response = self.api_client.post(self.url, data={"trees": []}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_curator_key_then_403(self):
        curator = APIClient()
        curator.credentials(HTTP_X_API_KEY=settings.CURATION_API_KEY)

        response = curator.post(self.url, data=self._body([("canonical", [POP, ROCK])]), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_merge_failure_then_nothing_applied_and_run_cleaned_up(self):
        body = self._body([("canonical", [POP, ROCK])], exported_on=export_curation(self.pipeline))

        with patch("grow.genre_tree.bulk_import.merge.analyze", side_effect=RuntimeError("boom")):
            # Django-q runs the task inline under test, so the failure also surfaces on the request.
            self.pipeline.raise_request_exception = False
            self.pipeline.post(self.url, data=body, format="json")

        assert ImportAttempt.objects.get().state == ImportAttempt.State.FAILED
        assert not Genre.objects.filter(wikidata_id="Q373342").exists()
        assert not ImportRun.objects.exists()
        assert not GenreTreeImportPayload.objects.exists()

    def test_anonymous_then_401(self):
        assert APIClient().post(self.url, data={"trees": []}, format="json").status_code == 401


@pytest.mark.postgres
class TestGenreTreesImportRunPostgres(TestGenreTreesImportRun):
    """Same contract on Postgres, where the merge also analyzes the rewritten tables, plus the data-preservation cases."""

    def test_genre_moved_between_trees_then_keeps_pk_and_songs(self):
        self._import([("canonical", [POP, ROCK, FOLK]), ("regional", [{**BRITTANY, Fields.CHILDREN: []}])])
        folk = Genre.objects.get(wikidata_id="Q1342372")
        song = self.model_fixture_factory.create_song(title="Gwerz", genre=folk)

        self._import([("canonical", [POP, ROCK]), ("regional", [BRITTANY])])

        moved = Genre.objects.get(wikidata_id="Q1342372")
        assert moved.pk == folk.pk
        song.refresh_from_db()
        assert song.genre_id == folk.pk
        assert all(report.valid for report in verify_catalogue_counts().values())

    def test_canonical_import_without_user_then_rows_have_no_owner(self):
        self._import([("canonical", [POP, ROCK])])

        assert not Genre.objects.exclude(user=None).exists()
