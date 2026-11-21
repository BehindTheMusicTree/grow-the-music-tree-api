from uuid import uuid4

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("grow", "0153_genre_derivations_list")]
AFTER = [("grow", "0154_adopt_admin_genres_as_local_nodes")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


class TestCase(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _genre(self, apps, name, parent=None, **fields):
        model = apps.get_model("grow", "Genre")
        apps.get_model("the_music_tree_genre_kit", "CriteriaType").objects.get_or_create(
            pk=0, defaults={"label": "genre"}
        )
        # Historical models skip save() logic: a root is its own root, so its uuid is chosen up front.
        uuid = uuid4()
        with transaction.atomic():
            return model.objects.create(
                uuid=uuid,
                _name=name,
                type_id=0,
                tree_name="canonical",
                parent_id=parent.pk if parent else None,
                root_id=parent.root_id if parent else uuid,
                **fields,
            )

    def test_forward_then_app_created_genres_become_local_nodes_under_their_parents(self):
        apps = migrate(BEFORE)
        rock = self._genre(apps, "Rock", wikidata_id="Q1")
        mid = self._genre(apps, "Mïd Rock", parent=rock)
        leaf = self._genre(apps, "Leaf", parent=mid)
        taken = self._genre(apps, "Taken", parent=rock)
        apps.get_model("grow", "CurationEntry").objects.create(
            list_name="canonical_parent_additions", key="LOCAL:taken", values={"label": "Other"}, reason="r"
        )
        orphan = self._genre(apps, "Orphan")

        apps = migrate(AFTER)

        Genre = apps.get_model("grow", "Genre")
        assert Genre.objects.get(pk=mid.pk).wikidata_id == "LOCAL:mid-rock"
        assert Genre.objects.get(pk=leaf.pk).wikidata_id == "LOCAL:leaf"
        assert Genre.objects.get(pk=taken.pk).wikidata_id == "LOCAL:taken-2"
        assert Genre.objects.get(pk=mid.pk).is_manually_edited
        edges = dict(
            apps.get_model("grow", "GenreEdgeRule")
            .objects.filter(user=None, item_id__in=["LOCAL:mid-rock", "LOCAL:leaf", "LOCAL:taken-2"])
            .values_list("item_id", "parent_item_id")
        )
        assert edges == {"LOCAL:mid-rock": "Q1", "LOCAL:leaf": "LOCAL:mid-rock", "LOCAL:taken-2": "Q1"}
        addition = apps.get_model("grow", "CurationEntry").objects.get(
            list_name="canonical_parent_additions", key="LOCAL:leaf"
        )
        assert addition.values == {"label": "Leaf"}
        assert Genre.objects.get(pk=orphan.pk).wikidata_id is None

    def test_forward_then_mapped_and_excluded_genres_untouched(self):
        apps = migrate(BEFORE)
        edge_count = apps.get_model("grow", "GenreEdgeRule").objects.count()
        rock = self._genre(apps, "Rock", wikidata_id="Q1")
        excluded = self._genre(apps, "Excluded", parent=rock, is_excluded=True)

        apps = migrate(AFTER)

        assert apps.get_model("grow", "Genre").objects.get(pk=excluded.pk).wikidata_id is None
        assert apps.get_model("grow", "GenreEdgeRule").objects.count() == edge_count
