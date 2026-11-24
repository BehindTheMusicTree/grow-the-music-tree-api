import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from the_music_tree_genre_kit.genre_graph.models import GenreGraphDataset

from grow.genre_graph.service import DATASET_KEY
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationReviewItem import CurationReviewItem
from grow.model.curation.CurationSyncState import CurationSyncState
from tests.utils.AppApiClient import AppApiClient
from tests.utils.AppTestCase import AppTestCase

TARGETS = [
    {"id": "Q1", "label": "Same label", "tree": "canonical"},
    {"id": "Q2", "label": "Same label", "tree": "regional"},
    {"id": "LOCAL:sound", "label": "Local sound", "tree": "local"},
]


class TestGenreAliasTargets(AppTestCase):
    def create_legacy(self, key="legacy", label="Local sound"):
        return CurationEntry.objects.create(
            list_name="genre_alias", key=key, values={"wikidata_genre_name": label}, reason="original"
        )

    def publish(self):
        pipeline = self.api_client
        pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)
        response = pipeline.get(reverse("curation-export"), {"genre_alias_version": 2})
        assert response.status_code == 200
        payload = response.json()
        assert payload["genre_alias_version"] == 2
        CurationSyncState.objects.filter(pk=1).update(applied_export_on=parse_datetime(payload["exported_on"]))
        return payload

    def test_report_is_scoped_to_export_and_replays_idempotently(self):
        entry = self.create_legacy()
        untouched = self.create_legacy("untouched")
        export = self.publish()
        assert export["genre_alias"][0]["target_item_id"] == ""
        CurationEntry.objects.update_instance(entry, reason="edited after the export")

        issue = {
            "targetItemId": None,
            "lastKnownLabel": "Local sound",
            "reason": "alias_legacy_unmigrated",
            "evidence": {"legacyStatus": "unique", "candidateItemIds": ["LOCAL:sound"]},
            "exposure": {"recording": 1, "releaseGroup": 1, "artist": 0, "any": 1},
        }
        report = {
            "unresolvedGenreTagCount": 1,
            "genreAliasReview": {
                "curationExportedOn": export["exported_on"],
                "targets": TARGETS,
                "issues": [{**issue, "tag": key} for key in (entry.key, untouched.key)],
            },
        }
        url = reverse("import-runs-unresolved-genre-tags")
        assert self.api_client.post(url, report).status_code == 400
        GenreGraphDataset.objects.create(key=DATASET_KEY, payload={"curationExportedOn": export["exported_on"]})
        review = report["genreAliasReview"]
        bad_issue = {**issue, "tag": untouched.key, "lastKnownLabel": "Wrong label"}
        assert (
            self.api_client.post(url, {**report, "genreAliasReview": {**review, "issues": [bad_issue]}}).status_code
            == 400
        )
        response = self.api_client.post(url, report)
        assert response.status_code == 201, response.json()
        assert self.api_client.post(url, report).status_code == 200
        assert self.api_client.post(url, {**report, "unresolvedGenreTagCount": 2}).status_code == 400
        assert list(CurationReviewItem.objects.filter(list_name="genre_alias").values_list("key", flat=True)) == [
            untouched.key
        ]
        review_url = reverse("curation-review")
        admin = AppApiClient()
        assert admin.get(review_url).json() == []
        items = admin.get(review_url, {"genre_alias_version": 2}).json()
        assert items[0]["evidence"]["entryUuid"] == str(untouched.uuid)
        CurationEntry.objects.update_instance(untouched, reason="reviewed")
        assert not CurationReviewItem.objects.filter(list_name="genre_alias").exists()

    def test_write_preserves_selected_id_across_a_rename(self):
        state = CurationSyncState.load()
        state.genre_alias_publication = {"targets": TARGETS}
        state.save(update_fields=["genre_alias_publication"])
        entries = reverse("curation-entries", kwargs={"list_name": "genre_alias"})
        row = {"musicbrainz_genre_name": "alias", "reason": "curated"}
        assert self.api_client.post(entries, {"row": {**row, "wikidata_genre_name": "Same label"}}).status_code == 400
        response = self.api_client.post(entries, {"row": {**row, "target_item_id": "Q2"}})
        assert response.status_code == 201, response.json()
        result = response.json()
        assert result["row"] == {**row, "target_item_id": "Q2", "wikidata_genre_name": "Same label"}

        old_client = {
            **row,
            "musicbrainz_genre_name": "old-client",
            "target_item_id": "",
            "wikidata_genre_name": "Local sound",
        }
        response = self.api_client.post(entries, {"row": old_client})
        assert response.status_code == 201, response.json()
        assert response.json()["row"]["target_item_id"] == "LOCAL:sound"

        state.genre_alias_publication = {"targets": [{**TARGETS[1], "label": "New label"}]}
        state.save(update_fields=["genre_alias_publication"])
        entry = reverse("curation-entry", kwargs={"list_name": "genre_alias", "uuid": result["uuid"]})
        response = self.api_client.patch(entry, {"row": {"reason": "edited"}}, format="json")
        assert response.status_code == 200
        assert response.json()["row"]["target_item_id"] == "Q2"
        assert response.json()["row"]["wikidata_genre_name"] == "Same label"
        assert self.api_client.patch(entry, {"row": {"target_item_id": ""}}, format="json").status_code == 400
        v1 = self.api_client.get(reverse("curation-export")).json()
        assert "target_item_id" not in v1["genre_alias"][0]

    def test_picker_lists_both_eligible_homonyms_and_reports_unavailable_catalogue(self):
        url = reverse("genre-alias-targets")
        assert self.api_client.get(url, {"q": "Same label"}).status_code == 503
        state = CurationSyncState.load()
        state.genre_alias_publication = {
            "targets": TARGETS,
            "published_on": "2026-11-13T12:01:00+00:00",
            "curation_exported_on": "2026-11-13T12:00:00+00:00",
        }
        state.save(update_fields=["genre_alias_publication"])
        found = self.api_client.get(url, {"q": "Same label"})
        assert found.status_code == 200
        assert found.json()["results"] == TARGETS[:2]
        assert self.api_client.get(url, {"q": "LOCAL:sound"}).json()["results"] == TARGETS[2:]

    def test_backfill_checks_exact_candidates_and_preserves_old_row(self):
        entry = self.create_legacy()
        self.create_legacy("homonym", "Same label")
        state = CurationSyncState.load()
        state.genre_alias_publication = {"curation_exported_on": "2026-11-13T12:00:00+00:00", "targets": TARGETS}
        state.save(update_fields=["genre_alias_publication"])
        simulation = StringIO()
        call_command("backfill_genre_alias_targets", stdout=simulation)
        by_key = {row["key"]: row["status"] for row in json.loads(simulation.getvalue())["rows"]}
        assert by_key == {"homonym": "ambiguous", "legacy": "convertible"}
        with TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(simulation.getvalue())
            for status in ("updated", "already_migrated"):
                outcome = StringIO()
                call_command("backfill_genre_alias_targets", apply_plan=plan_path, stdout=outcome)
                assert json.loads(outcome.getvalue()) == {str(entry.uuid): status}
        entry.refresh_from_db()
        assert entry.row == {
            "musicbrainz_genre_name": "legacy",
            "wikidata_genre_name": "Local sound",
            "target_item_id": "LOCAL:sound",
            "reason": "original",
        }
