import uuid

import pytest
from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks
from the_music_tree_genre_kit.genre_graph.assignments import assignment_snapshot
from the_music_tree_genre_kit.genre_graph.models import (
    GenreGraphAssignmentState,
    GenreGraphAttributionRevision,
    GenreGraphDataset,
)

from grow.model.playlist.children.criteria.CriteriaPlaylist import CriteriaPlaylist
from grow.model.song.Song import Song
from tests.integration.track.song.test_song_import_runs import MBID, OTHER_MBID, RUNS, SONG, _gzip_ndjson
from tests.utils.AppTestCase import AppTestCase
from tests.utils.song_graph import install_song_graph

EVIDENCE = {"decisionId": "merge-test", "source": "fixture", "rationale": "Reviewed"}
NO_GENRE = {k: v for k, v in SONG.items() if k not in {"genre_name", "genre_wikidata_id"}}


@pytest.mark.postgres
class TestSemanticImportMerge(AppTestCase):
    def setUp(self):
        super().setUp()
        self.rock = self.model_fixture_factory.create_genre("Rock")
        self.jazz = self.model_fixture_factory.create_genre("Jazz")
        self.existing = self.model_fixture_factory.create_song(
            title="Old", genre=self.jazz, musicbrainz_recording_id=OTHER_MBID
        )
        self.dataset = install_song_graph({self.rock: [], self.jazz: [self.existing]})

    def _identity(self, genre) -> str:
        return f"LOCAL:{genre.pk}"

    def _run(
        self, songs: list[dict], assignments: dict[str, list[str] | None], before_commit=None, **overrides
    ) -> dict:
        self.dataset.refresh_from_db()
        metadata = {
            "graph_revision": str(overrides.pop("graph", self.dataset.revision)),
            "membership_revision": str(self.dataset.membership_revision),
            "expected_parts": {"songs": 1, "assignments": 1},
            **overrides,
        }
        run_id = self.api_client.post(path=RUNS, data=metadata).data["run_id"]
        rows = [
            {"musicbrainz_recording_id": m, "assignments": {i: [EVIDENCE] for i in ids}}
            for m, ids in assignments.items()
        ]
        for url, body in (("parts/0/", songs), ("assignments/parts/0/", rows)):
            response = self.api_client.put(
                path=f"{RUNS}{run_id}/{url}",
                data=_gzip_ndjson(body),
                format=None,
                content_type="application/x-ndjson",
                HTTP_CONTENT_ENCODING="gzip",
            )
            assert response.status_code == status.HTTP_200_OK, response.content
        if before_commit:
            before_commit()
        response = self.api_client.post(path=f"{RUNS}{run_id}/commit/")
        if before_commit:
            return response
        assert response.status_code == status.HTTP_202_ACCEPTED, response.content
        task = self.api_client.get(path=reverse("song-list") + f"songs/import/{response.data['task_id']}/status/")
        return task.data

    def test_new_changed_and_empty_songs_publish_assignments_and_leave_the_legacy_column(self):
        changed = {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "Old"}
        empty = {
            **NO_GENRE,
            "musicbrainz_recording_id": str(uuid.uuid4()),
            "title": "Empty",
            "youtube_video_id": "zzz111yyyxx",
        }
        data = self._run(
            [SONG, changed, empty],
            {
                MBID: [self._identity(self.rock)],
                OTHER_MBID: [self._identity(self.rock)],
                empty["musicbrainz_recording_id"]: [],
            },
        )
        assert data["status"] == "success", data
        assert data["result"]["imported"] == 3 and data["result"]["skipped"] == 0
        assert "publish_assignments" in [t["label"] for t in data["result"]["stepTimings"]]

        new = Song.objects.get(musicbrainz_recording_id=MBID)
        assert new.genre_id is None  # the legacy column is never written by a reviewed run
        assert set(assignment_snapshot(dataset=self.dataset, track_id=new.pk)) == {self._identity(self.rock)}
        assert list(
            TrackPlaylistRel.objects.filter(playlist=self.rock.criteria_playlist)
            .values_list("track_id", flat=True)
            .order_by("track_id")
        ) == sorted([new.pk, self.existing.pk])
        genreless = CriteriaPlaylist.objects.get(
            criteria__isnull=True, user__isnull=True, type_id=CriteriaTypePks.GENRE.value
        )
        assert list(TrackPlaylistRel.objects.filter(track__title="Empty").values_list("playlist_id", flat=True)) == [
            genreless.pk
        ]
        assert assignment_snapshot(dataset=self.dataset, track_id=Song.objects.get(title="Empty").pk) == {}
        self.existing.refresh_from_db()
        assert self.existing.genre_id == self.jazz.pk
        assert GenreGraphAttributionRevision.objects.filter(track_id=self.existing.pk).count() >= 2

    def test_locked_song_keeps_its_assignment(self):
        Song.objects.filter(pk=self.existing.pk).update(is_manually_edited=True)
        data = self._run([{**SONG, "musicbrainz_recording_id": OTHER_MBID}], {OTHER_MBID: [self._identity(self.rock)]})
        assert data["status"] == "success", data
        assert set(assignment_snapshot(dataset=self.dataset, track_id=self.existing.pk)) == {self._identity(self.jazz)}
        assert GenreGraphAssignmentState.objects.filter(track_id=self.existing.pk).count() == 1

    def test_stale_graph_revision_fails_without_writing(self):
        data = self._run(
            [SONG],
            {MBID: []},
            before_commit=lambda: GenreGraphDataset.objects.filter(pk=self.dataset.pk).update(revision=uuid.uuid4()),
        )
        assert data.status_code == status.HTTP_409_CONFLICT
        assert not Song.objects.filter(musicbrainz_recording_id=MBID).exists()

    def test_legacy_run_is_refused_while_a_graph_is_active(self):
        response = self.api_client.post(path=RUNS, data={})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Song.objects.filter(musicbrainz_recording_id=MBID).exists()
