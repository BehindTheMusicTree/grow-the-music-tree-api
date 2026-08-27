from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework import status

from tests.utils.AppApiClient import AppApiClient
from tests.utils.restore_kit_seeded_data import restore_kit_seeded_data, snapshot_kit_seeded_data


class TestLoadExampleIdempotent(TransactionTestCase):
    """
    Uses TransactionTestCase (real commits) rather than TestCase: SQLite only
    enforces Track.genre's FK on commit, so TestCase's savepoint-wrapped tests
    never actually hit the constraint violation a second `tree/load-example`
    call triggers against tracks left over from the first (Track.genre is
    on_delete=DO_NOTHING, so wiping the old genre tree doesn't clear them).
    """

    serialized_rollback = True

    def _fixture_teardown(self):
        # `the_music_tree_genre_kit` has no top-level models.py, so `serialized_rollback`
        # can never capture its tables; the real flush below permanently wipes CriteriaType
        # and Playlist rows unless we put them back for whatever test runs next.
        snapshot = snapshot_kit_seeded_data()
        super()._fixture_teardown()
        restore_kit_seeded_data(snapshot)

    def test_load_example_tree_twice_does_not_violate_track_genre_fk(self):
        api_client = AppApiClient()
        url = reverse("genre-list") + "tree/load-example/"

        first_response = api_client.post(path=url)
        assert first_response.status_code == status.HTTP_201_CREATED

        second_response = api_client.post(path=url)
        assert second_response.status_code == status.HTTP_201_CREATED
