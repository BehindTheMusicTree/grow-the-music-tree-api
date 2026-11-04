from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("grow", "0089_region_overrides_curation_list")]
AFTER = [("grow", "0090_region_map_tileset_index")]


class TestCase(TransactionTestCase):
    def tearDown(self):
        MigrationExecutor(connection).migrate(AFTER)
        super().tearDown()

    def test_drops_geometry_snapshots_when_it_is_the_only_pending_migration(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        apps = executor.loader.project_state(BEFORE).apps
        file = apps.get_model("grow", "RegionMapFile").objects.create(sha256="a" * 64, body=b"{}", size=2)
        snapshot = apps.get_model("grow", "RegionMapSnapshot").objects.create(checksum="c" * 64)
        apps.get_model("grow", "RegionMapSnapshotFile").objects.create(
            snapshot=snapshot, file=file, path="geometry/Q1.geojson"
        )

        # The command, unlike a bare executor, renders the pre-migrate state that kept the stale reverse relation.
        call_command("migrate", "grow", AFTER[0][1], verbosity=0)

        apps = MigrationExecutor(connection).loader.project_state(AFTER).apps
        assert not apps.get_model("grow", "RegionMapSnapshot").objects.exists()
        assert not apps.get_model("grow", "RegionMapFile").objects.exists()
        assert "grow_region_map_snapshot_file" not in connection.introspection.table_names()
