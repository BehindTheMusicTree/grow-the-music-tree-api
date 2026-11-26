from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TransactionTestCase
from the_music_tree_genre_kit.criteria.type.CriteriaType import CriteriaType

from grow.bulk_import.ImportAttempt import ImportAttempt
from grow.genre_music.catalogue_verification import verify_catalogue_counts
from grow.management.commands.reset_catalogue import wiped_tables
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.curation.CurationSyncState import CurationSyncState
from grow.model.curation.GenreEdgeRule import GenreEdgeRule
from grow.model.genre_tree_version.GenreTreeVersion import GenreTreeVersion
from grow.model.history.HistoryEntry import HistoryEntry
from grow.model.pipeline_run.PipelineRunRequest import PipelineRunRequest
from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.song.Song import Song
from tests.utils.ModelFixtureFactory import ModelFixtureFactory

pytestmark = pytest.mark.postgres

A = "Q1"
B = "Q2"


def count(table: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")
        return cursor.fetchone()[0]


class TestResetCatalogue(TransactionTestCase):
    def setUp(self):
        CriteriaType.objects.get_or_create(pk=0, defaults={"label": "genre"})
        CriteriaType.objects.get_or_create(pk=1, defaults={"label": "tag"})
        GenreTreeVersion.objects.get_or_create(pk=1, defaults={"token": uuid4()})
        CriteriaPlaylist.objects.ensure_criterialess(None)
        self.admin = User.objects.create(username="admin-sub")
        factory = ModelFixtureFactory(default_user=None)
        genre = factory.create_genre("Rock")
        factory.create_song("Song", genre)
        self.entry = CurationEntry.objects.create(
            list_name="genre_alias",
            key="k",
            values={"wikidata_genre_name": "x", "target_item_id": "LOCAL:sound"},
            reason="original",
        )
        GenreEdgeRule.objects.upsert("classification", A, B, action="assert")
        PipelineRunRequest.objects.create(kind=PipelineRunRequest.Kind.FULL, status=PipelineRunRequest.Status.SUCCEEDED)

    def reset(self, *args, **kwargs):
        out = StringIO()
        call_command("reset_catalogue", *args, confirm=connection.settings_dict["NAME"], stdout=out, **kwargs)
        return out.getvalue()

    def curation_history_ids(self) -> set:
        types = ContentType.objects.get_for_models(CurationEntry, GenreEdgeRule).values()
        return set(HistoryEntry.objects.filter(content_type__in=types).values_list("pk", flat=True))

    def test_wipes_the_catalogue_and_keeps_curation(self):
        kept_history = self.curation_history_ids()
        assert kept_history and HistoryEntry.objects.exclude(pk__in=kept_history).exists()
        entry_created = CurationEntry.objects.values_list("pk", "created_on").get()
        token = GenreTreeVersion.objects.get(pk=1).token
        CurationSyncState.objects.update_or_create(pk=1, defaults={"applied_export_on": "2026-01-01T00:00:00Z"})

        self.reset()

        assert Song.objects.count() == 0
        emptied = [t for t in wiped_tables() if t not in ("grow_history_entry", "grow_curation_sync_state")]
        assert [count(t) for t in emptied] == [0] * len(emptied)
        assert set(HistoryEntry.objects.values_list("pk", flat=True)) == kept_history
        assert CurationEntry.objects.values_list("pk", "created_on").get() == entry_created
        assert GenreEdgeRule.objects.count() == 1
        assert PipelineRunRequest.objects.count() == 1
        assert CurationSyncState.objects.get(pk=1).applied_export_on is None
        assert GenreTreeVersion.objects.get(pk=1).token != token
        assert CriteriaType.objects.count() == 2
        verify_catalogue_counts()

    def test_creates_criterialess_playlists_idempotently(self):
        self.reset()
        assert CriteriaPlaylist.objects.count() == 0
        CriteriaPlaylist.objects.ensure_criterialess(None)
        CriteriaPlaylist.objects.ensure_criterialess(None)
        assert CriteriaPlaylist.objects.filter(criteria=None).count() == 2

    def test_dry_run_changes_nothing(self):
        output = self.reset(dry_run=True)
        assert "grow_song" in output and "Dry run" in output
        assert Song.objects.count() == 1

    def test_wrong_confirm_then_refused(self):
        with pytest.raises(CommandError, match="--confirm"):
            call_command("reset_catalogue", confirm="other")
        assert Song.objects.count() == 1

    def test_running_pipeline_request_then_refused(self):
        PipelineRunRequest.objects.create(kind=PipelineRunRequest.Kind.FULL, status=PipelineRunRequest.Status.RUNNING)
        with pytest.raises(CommandError, match="queued or running"):
            self.reset()
        assert Song.objects.count() == 1

    def test_pending_import_then_refused(self):
        ImportAttempt.objects.create(run_id=1, task_id="t", kind="songs", mode="full", attempt=1)
        with pytest.raises(CommandError, match="imports still pending"):
            self.reset()
        assert Song.objects.count() == 1

    def test_finished_import_does_not_block(self):
        ImportAttempt.objects.create(
            run_id=1, task_id="t", kind="songs", mode="full", attempt=1, state=ImportAttempt.State.SUCCEEDED
        )
        self.reset()
        assert Song.objects.count() == 0

    def test_user_data_then_refused_unless_included(self):
        CriteriaPlaylist.objects.ensure_criterialess(self.admin)
        ModelFixtureFactory(default_user=self.admin).create_song("Mine", None, user=self.admin)
        with pytest.raises(CommandError, match="user data"):
            self.reset()
        assert Song.objects.count() == 2
        self.reset(include_user_data=True)
        assert Song.objects.count() == 0
