from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("grow", "0151_canonical_roots_list")]
AFTER = [("grow", "0152_song_genre_provenance")]
MBID = "11111111-1111-4111-8111-111111111111"


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


class TestCase(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_forward_then_legacy_rule_gets_a_deterministic_provenance(self):
        apps = migrate(BEFORE)
        Entry = apps.get_model("grow", "CurationEntry")
        Entry.objects.create(list_name="song_genre", key=MBID, values={"genre_item_id": "Q1"}, reason="")
        Entry.objects.create(
            list_name="song_genre", key="other", values={"genre_item_id": "Q2", "decision_id": "admin-x"}, reason="r"
        )

        apps = migrate(AFTER)

        Entry = apps.get_model("grow", "CurationEntry")
        legacy = Entry.objects.get(list_name="song_genre", key=MBID)
        assert legacy.values == {
            "genre_item_id": "Q1",
            "decision_id": f"legacy-song-genre:{MBID}",
            "decision_source": "curation-legacy",
        }
        assert legacy.reason == "Recorded before provenance was required"
        assert Entry.objects.get(list_name="song_genre", key="other").values["decision_id"] == "admin-x"

    def test_backward_then_provenance_keys_are_removed(self):
        apps = migrate(AFTER)
        apps.get_model("grow", "CurationEntry").objects.create(
            list_name="song_genre",
            key=MBID,
            values={"genre_item_id": "Q1", "decision_id": "d", "decision_source": "s"},
            reason="why",
        )

        apps = migrate(BEFORE)

        entry = apps.get_model("grow", "CurationEntry").objects.get(list_name="song_genre", key=MBID)
        assert entry.values == {"genre_item_id": "Q1"}
