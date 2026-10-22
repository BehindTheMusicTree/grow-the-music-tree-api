from importlib import import_module

from django.apps import apps
from django.urls import reverse
from rest_framework import status

from grow.curation.rows import InvalidRow
from grow.model.curation.CurationEntry import CurationEntry
from tests.utils.AppTestCase import AppTestCase

migration = import_module("grow.migrations.0065_curation_list_renames_and_precedence_qids")
MB_ID = "11111111-1111-4111-8111-111111111111"


class TestCase(AppTestCase):
    def _genre(self, name: str, wikidata_id: str, **kwargs):
        return self.model_fixture_factory.create_genre(name, wikidata_id=wikidata_id, **kwargs)

    def _umbrella_row(self, wikidata_id: str) -> dict[str, str]:
        return {"item_id": wikidata_id, "item_label": "x", "reason": "r"}

    def test_assign_umbrella_genre_then_400_and_nothing_written(self):
        techno = self._genre("Techno", "Q9", is_umbrella=True)
        recording = self.model_fixture_factory.create_recording("Song", None, musicbrainz_recording_id=MB_ID)

        response = self.api_client.post(
            path=reverse("recording-assign-genre"),
            data={"recordings": [str(recording.uuid)], "genre": str(techno.uuid)},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not CurationEntry.objects.filter(list_name="recording_genre").exists()
        recording.refresh_from_db()
        assert recording.genre is None

    def test_umbrella_entry_for_leaf_then_invalid_row(self):
        self._genre("Brostep", "Q1")

        with self.assertRaises(InvalidRow) as raised:
            CurationEntry.objects.upsert("umbrella_genres", self._umbrella_row("Q1"))

        assert "no sub-genre" in str(raised.exception.errors)

    def test_umbrella_entry_for_genre_with_child_then_created(self):
        techno = self._genre("Techno", "Q9")
        self._genre("Detroit techno", "Q10", parent=techno)

        assert CurationEntry.objects.upsert("umbrella_genres", self._umbrella_row("Q9")) == "created"

    def test_umbrella_entry_for_unknown_genre_then_created(self):
        assert CurationEntry.objects.upsert("umbrella_genres", self._umbrella_row("Q404")) == "created"

    def test_recordings_filtered_by_umbrella_genre(self):
        techno = self._genre("Techno", "Q9", is_umbrella=True)
        detroit = self._genre("Detroit techno", "Q10", parent=techno)
        coarse = self.model_fixture_factory.create_recording("Coarse", techno)
        self.model_fixture_factory.create_recording("Fine", detroit)

        response = self.api_client.get(path=reverse("recording-list"), data={"genre_is_umbrella": "true"})

        assert [r["uuid"] for r in response.json()["results"]] == [str(coarse.uuid)]

    def test_precedence_migration_converts_names_to_qids_and_drops_lineage_pairs(self):
        rock = self._genre("Rock", "Q11399")
        pop = self._genre("Pop", "Q37073")
        self._genre("Pop rock", "Q484641", parent=pop)
        self._genre("Punk rock", "Q3071", parent=rock)
        reason = "r"
        CurationEntry.objects.create(
            user=None, list_name="genre_alias", key="punk", values={"wikidata_genre_name": "Punk rock"}
        )
        for key in ("pop rock\tpop", "pop rock\trock", "punk\tpop", "punk\trock"):
            CurationEntry.objects.create(user=None, list_name="genre_precedence", key=key, values={}, reason=reason)

        migration.convert_precedence(apps, None)

        keys = sorted(CurationEntry.objects.filter(list_name="genre_precedence").values_list("key", flat=True))
        assert keys == ["Q3071\tQ37073", "Q484641\tQ11399"]

    def test_precedence_migration_unresolvable_name_then_pair_dropped(self):
        self._genre("Rock", "Q11399")
        self._genre("Pop punk", "Q1", parent=self._genre("Punk rock", "Q3071"))
        for key in ("nope\trock", "pop punk\tpunk rock"):
            CurationEntry.objects.create(user=None, list_name="genre_precedence", key=key, values={}, reason="r")

        migration.convert_precedence(apps, None)

        assert list(CurationEntry.objects.filter(list_name="genre_precedence").values_list("key", flat=True)) == []

    def test_precedence_migration_music_suffix_then_resolved(self):
        self._genre("Rock music", "Q11399")
        self._genre("Punk rock", "Q3071")
        CurationEntry.objects.create(
            user=None, list_name="genre_precedence", key="punk rock\trock", values={}, reason="r"
        )

        migration.convert_precedence(apps, None)

        assert list(CurationEntry.objects.filter(list_name="genre_precedence").values_list("key", flat=True)) == [
            "Q3071\tQ11399"
        ]
