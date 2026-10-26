import gzip
import json
import uuid

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel

from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.model.artist.Artist import Artist
from grow.model.import_run.ImportRun import ImportRun
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.recording.Recording import Recording
from grow.track.bulk_import.SongImportStaging import SongImportStaging
from tests.utils.AppTestCase import AppTestCase

MBID = "b1a9c0e9-d987-4042-ae91-78d6a3267d69"
OTHER_MBID = "0c4b2a83-6a5c-4c1d-9f43-3b9d8f0b2e11"
SONG = {
    "musicbrainz_recording_id": MBID,
    "title": "Comfortably Numb",
    "artist": "Pink Floyd",
    "youtube_video_id": "abc123defgh",
    "youtube_unplayable_reason": None,
    "genre_name": "Rock",
    "first_release_year": None,
}
ARTIST_MBID = "83d91898-7763-47d7-b03b-b92132375c47"
RUNS = reverse("recording-list") + "songs/import-runs/"


def _gzip_ndjson(songs: list[dict]) -> bytes:
    return gzip.compress("".join(json.dumps(song) + "\n" for song in songs).encode())


class TestImportRunProtocol(AppTestCase):
    def _create_run(self) -> int:
        response = self.api_client.post(path=RUNS)
        assert response.status_code == status.HTTP_201_CREATED
        return response.data["run_id"]

    def test_create_run_abandons_earlier_runs(self):
        first = self._create_run()
        SongImportStaging.objects.create(
            run_id=first, part=0, musicbrainz_recording_id=MBID, title="t", artist="a", genre_name=None
        )

        committed = BulkImportRun.objects.create(kind=ImportRun.Kind.SONGS, committed_on=timezone.now())
        SongImportStaging.objects.create(
            run_id=committed.pk, part=0, musicbrainz_recording_id=MBID, title="t", artist="a", genre_name=None
        )

        second = self._create_run()

        assert sorted(BulkImportRun.objects.values_list("pk", flat=True)) == [committed.pk, second]
        assert list(SongImportStaging.objects.values_list("run_id", flat=True)) == [committed.pk]

    def test_create_run_with_unknown_mode_then_400(self):
        assert self.api_client.post(path=RUNS, data={"mode": "partial"}).status_code == status.HTTP_400_BAD_REQUEST

    def test_deletions_on_full_run_then_400(self):
        run_id = self._create_run()

        response = self.api_client.put(
            path=f"{RUNS}{run_id}/deletions/", data=b"", format=None, content_type="application/x-ndjson"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.postgres
    def test_invalid_deletion_then_400_and_nothing_staged(self):
        run_id = self.api_client.post(path=RUNS, data={"mode": "delta"}).data["run_id"]

        for body in (b"not gzip", _gzip_ndjson([{"musicbrainz_recording_id": "nope"}]), _gzip_ndjson([{"id": MBID}])):
            response = self.api_client.put(
                path=f"{RUNS}{run_id}/deletions/",
                data=body,
                format=None,
                content_type="application/x-ndjson",
                HTTP_CONTENT_ENCODING="gzip",
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not BulkImportDeletion.objects.exists()

    def test_commit_unknown_run_then_404(self):
        assert self.api_client.post(path=f"{RUNS}999/commit/").status_code == status.HTTP_404_NOT_FOUND

    def test_part_or_commit_on_committed_run_then_400(self):
        run_id = self._create_run()
        BulkImportRun.objects.filter(pk=run_id).update(committed_on="2026-01-01T00:00:00Z")

        part = self.api_client.put(
            path=f"{RUNS}{run_id}/parts/0/", data=b"", format=None, content_type="application/x-ndjson"
        )
        commit = self.api_client.post(path=f"{RUNS}{run_id}/commit/")

        assert (part.status_code, commit.status_code) == (status.HTTP_400_BAD_REQUEST, status.HTTP_400_BAD_REQUEST)

    def test_status_reports_pending_for_unknown_task(self):
        response = self.api_client.get(path=reverse("recording-list") + "songs/import/does-not-exist/status/")

        assert response.data["status"] == "pending"

    def test_list_includes_tracks_without_video_but_hides_genreless(self):
        genre = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_recording(title="Kept", genre=genre, youtube_video_id="abc123defgh")
        self.model_fixture_factory.create_recording(title="No video", genre=genre, youtube_video_id=None)
        self.model_fixture_factory.create_recording(title="No genre", genre=None, youtube_video_id="xyz789uvwab")

        response = self.api_client.get(path=reverse("recording-list"))

        assert sorted(track["title"] for track in response.json()["results"]) == ["Kept", "No video"]


@pytest.mark.postgres
class TestImportRunMerge(AppTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = APIClient()
        self.pipeline.credentials(HTTP_X_API_KEY=settings.PIPELINE_API_KEY)

    def _upload(self, run_id: int, part: int, body: bytes, client=None):
        return (client or self.api_client).put(
            path=f"{RUNS}{run_id}/parts/{part}/",
            data=body,
            format=None,
            content_type="application/x-ndjson",
            HTTP_CONTENT_ENCODING="gzip",
        )

    def _upload_deletions(self, run_id: int, deleted: tuple[str, ...], client=None):
        body = _gzip_ndjson([{"musicbrainz_recording_id": mbid} for mbid in deleted])
        return (client or self.api_client).put(
            path=f"{RUNS}{run_id}/deletions/",
            data=body,
            format=None,
            content_type="application/x-ndjson",
            HTTP_CONTENT_ENCODING="gzip",
        )

    def _sync(self, *parts: list[dict], client=None, mode: str = "full", deleted: tuple[str, ...] = ()) -> dict:
        client = client or self.api_client
        run_id = client.post(path=RUNS, data={"mode": mode}).data["run_id"]
        for part, songs in enumerate(parts):
            response = self._upload(run_id, part, _gzip_ndjson(songs), client)
            assert response.status_code == status.HTTP_200_OK, response.content
            assert response.data["count"] == len(songs)
        if deleted:
            response = self._upload_deletions(run_id, deleted, client)
            assert response.status_code == status.HTTP_200_OK, response.content
        response = client.post(path=f"{RUNS}{run_id}/commit/")
        assert response.status_code == status.HTTP_202_ACCEPTED
        task = self.api_client.get(path=reverse("recording-list") + f"songs/import/{response.data['task_id']}/status/")
        assert task.data["status"] == "success", task.data
        return task.data["result"]

    def _playlist_tracks(self, genre) -> list[str]:
        return list(
            TrackPlaylistRel.objects.filter(playlist=genre.criteria_playlist)
            .order_by("position")
            .values_list("track__title", flat=True)
        )

    def test_import_creates_songs_with_and_without_video_or_genre(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        songs = [
            SONG,
            {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "No video", "youtube_video_id": None},
            {**SONG, "musicbrainz_recording_id": str(uuid.uuid4()), "title": "No genre", "genre_name": None},
            {**SONG, "musicbrainz_recording_id": str(uuid.uuid4()), "title": "Unknown", "genre_name": "Nope"},
        ]

        assert self._sync(songs[:2], songs[2:]) == {"imported": 4, "skipped": 1}

        track = Recording.objects.get(musicbrainz_recording_id=MBID)
        assert (track.title, track.genre_id, track.youtube_video_id) == ("Comfortably Numb", rock.pk, "abc123defgh")
        assert [a.name for a in track.artists.all()] == ["Pink Floyd"]
        assert Recording.objects.get(title="No video").youtube_video_id is None
        assert Recording.objects.get(title="No genre").genre is None
        assert Recording.objects.get(title="Unknown").genre is None
        assert self._playlist_tracks(rock) == ["Comfortably Numb"]
        assert not SongImportStaging.objects.exists() and not BulkImportRun.objects.exists()

    def test_first_release_year_imported_updated_and_nullable(self):
        self.model_fixture_factory.create_genre("Rock")
        unknown_year = {**SONG, "musicbrainz_recording_id": OTHER_MBID}

        self._sync([{**SONG, "first_release_year": 1979}, unknown_year])

        def years():
            return dict(Recording.objects.values_list("musicbrainz_recording_id", "first_release_year"))

        assert years() == {uuid.UUID(MBID): 1979, uuid.UUID(OTHER_MBID): None}

        self._sync([{**SONG, "first_release_year": 1980}, {**unknown_year, "first_release_year": 1975}])

        assert years() == {uuid.UUID(MBID): 1980, uuid.UUID(OTHER_MBID): 1975}

    def test_import_accepts_musicbrainz_length_title_and_artist(self):
        self.model_fixture_factory.create_genre("Rock")
        song = {**SONG, "title": "t" * 1059, "artist": "a" * 1018}

        assert self._sync([song]) == {"imported": 1, "skipped": 0}

        track = Recording.objects.get(musicbrainz_recording_id=MBID)
        assert track.title == song["title"]
        assert [a.name for a in track.artists.all()] == [song["artist"]]

    def test_import_resolves_genre_case_insensitively_into_ascendant_playlists(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        prog = self.model_fixture_factory.create_genre("Progressive Rock", parent=rock)

        self._sync([{**SONG, "genre_name": "progressive rock"}])

        assert Recording.objects.get().genre_id == prog.pk
        assert self._playlist_tracks(prog) == self._playlist_tracks(rock) == ["Comfortably Numb"]

    def test_reimport_updates_in_place_and_moves_playlists(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        pop = self.model_fixture_factory.create_genre("Pop")
        self._sync([SONG, {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "Other"}])
        track = Recording.objects.get(musicbrainz_recording_id=MBID)

        self._sync(
            [
                {**SONG, "genre_name": "Pop", "youtube_unplayable_reason": "not_embeddable"},
                {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "Other"},
            ]
        )

        moved = Recording.objects.get(musicbrainz_recording_id=MBID)
        assert (moved.uuid, moved.genre_id, moved.youtube_unplayable_reason) == (track.uuid, pop.pk, "not_embeddable")
        assert self._playlist_tracks(rock) == ["Other"]
        assert self._playlist_tracks(pop) == []
        assert list(
            TrackPlaylistRel.objects.filter(playlist=rock.criteria_playlist).values_list("position", flat=True)
        ) == [1]

    def test_playability_change_adds_or_drops_rels_and_closes_gaps(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        prog = self.model_fixture_factory.create_genre("Progressive Rock", parent=rock)
        third = {**SONG, "musicbrainz_recording_id": str(uuid.uuid4()), "title": "Third", "genre_name": "Rock"}
        other = {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "Other", "youtube_video_id": None}
        self._sync([{**SONG, "genre_name": "Progressive Rock"}, other, third])
        assert sorted(self._playlist_tracks(rock)) == ["Comfortably Numb", "Third"]

        self._sync([{**SONG, "genre_name": "Progressive Rock", "youtube_video_id": None}, other, third])
        assert self._playlist_tracks(rock) == ["Third"]
        assert self._playlist_tracks(prog) == []
        assert list(
            TrackPlaylistRel.objects.filter(playlist=rock.criteria_playlist).values_list("position", flat=True)
        ) == [1]

        self._sync(
            [
                SONG,
                {**other, "youtube_video_id": "zzz123defgh"},
                {**third, "youtube_unplayable_reason": "not_embeddable"},
            ]
        )
        assert sorted(self._playlist_tracks(rock)) == ["Comfortably Numb", "Other"]
        assert self._playlist_tracks(prog) == []

    def _genreless_tracks(self) -> list[str]:
        return list(
            TrackPlaylistRel.objects.filter(playlist=GenrePlaylist.objects.get(user=None, criteria=None))
            .order_by("position")
            .values_list("track__title", flat=True)
        )

    def test_genreless_playlist_follows_genre_and_playability(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        playable = {**SONG, "genre_name": None}
        no_video = {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "No video", "genre_name": None}
        no_video["youtube_video_id"] = None
        rocker = {**SONG, "musicbrainz_recording_id": str(uuid.uuid4()), "title": "Rocker"}
        self._sync([playable, no_video, rocker])
        assert self._genreless_tracks() == ["Comfortably Numb"]

        self._sync([playable, {**no_video, "youtube_video_id": "zzz123defgh"}, {**rocker, "genre_name": None}])
        genreless = self._genreless_tracks()
        assert sorted(genreless[:2]) == ["No video", "Rocker"] and genreless[2] == "Comfortably Numb"
        assert self._playlist_tracks(rock) == []

        self._sync(
            [
                {**playable, "youtube_unplayable_reason": "private"},
                {**no_video, "youtube_video_id": "zzz123defgh", "genre_name": "Rock"},
                {**rocker, "genre_name": None},
            ]
        )
        assert self._genreless_tracks() == ["Rocker"]
        assert self._playlist_tracks(rock) == ["No video"]
        assert list(
            TrackPlaylistRel.objects.filter(playlist=GenrePlaylist.objects.get(user=None, criteria=None)).values_list(
                "position", flat=True
            )
        ) == [1]

    def test_new_tracks_take_first_positions(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        self._sync([SONG])

        self._sync([SONG, {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "Newer"}])

        assert self._playlist_tracks(rock) == ["Newer", "Comfortably Numb"]

    def test_stale_tracks_deleted_but_locked_kept_with_their_genre(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        pop = self.model_fixture_factory.create_genre("Pop")
        locked = self.model_fixture_factory.create_recording(
            title="Locked", genre=pop, musicbrainz_recording_id=OTHER_MBID, is_manually_edited=True
        )
        self.model_fixture_factory.create_recording(title="Locked absent", genre=pop, is_manually_edited=True)
        self.model_fixture_factory.create_recording(title="Stale", genre=rock, youtube_video_id="stalevideo1")

        self._sync([SONG, {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "Renamed"}])

        titles = sorted(Recording.objects.values_list("title", flat=True))
        assert titles == ["Comfortably Numb", "Locked absent", "Renamed"]
        locked.refresh_from_db()
        assert (locked.title, locked.genre_id) == ("Renamed", pop.pk)

    def test_delta_run_upserts_without_deleting_unlisted_tracks(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        self.model_fixture_factory.create_recording(title="Unlisted", genre=rock, youtube_video_id="stalevideo1")

        self._sync([SONG], mode="delta")
        result = self._sync([{**SONG, "title": "Renamed"}], mode="delta")

        assert result == {"imported": 1, "skipped": 0}
        assert sorted(Recording.objects.values_list("title", flat=True)) == ["Renamed", "Unlisted"]

    def test_delta_run_deletes_only_listed_unlocked_tracks(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        third = "5d2f8f7e-1f0a-4a3b-8f7e-0a1b2c3d4e5f"
        self._sync(
            [
                SONG,
                {**SONG, "musicbrainz_recording_id": OTHER_MBID, "title": "Other", "youtube_video_id": "othervideo1"},
                {**SONG, "musicbrainz_recording_id": third, "title": "Third", "youtube_video_id": "thirdvideo1"},
            ]
        )
        Recording.objects.filter(musicbrainz_recording_id=OTHER_MBID).update(is_manually_edited=True)
        self.model_fixture_factory.create_recording(title="Unlisted", genre=rock, youtube_video_id="stalevideo1")

        self._sync([], mode="delta", deleted=(MBID, OTHER_MBID))

        assert sorted(Recording.objects.values_list("title", flat=True)) == ["Other", "Third", "Unlisted"]

    def test_delta_run_with_nothing_to_do_succeeds(self):
        self.model_fixture_factory.create_recording(title="Kept", genre=None)

        assert self._sync([], mode="delta") == {"imported": 0, "skipped": 0}
        assert Recording.objects.count() == 1

    def test_legacy_track_adopted_by_video_id(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        legacy = self.model_fixture_factory.create_recording(
            title="Comfortably Numb", genre=rock, youtube_video_id="abc123defgh"
        )

        self._sync([SONG])
        self._sync([{**SONG, "youtube_video_id": "xyz789uvwab"}])

        track = Recording.objects.get()
        assert (track.uuid, track.youtube_video_id) == (legacy.uuid, "xyz789uvwab")

    def test_reuploaded_part_replaces_its_rows(self):
        self.model_fixture_factory.create_genre("Rock")
        run_id = self.api_client.post(path=RUNS).data["run_id"]
        self._upload(run_id, 0, _gzip_ndjson([{**SONG, "title": "First"}]))

        assert self._upload(run_id, 0, _gzip_ndjson([SONG])).data["count"] == 1

        assert list(SongImportStaging.objects.values_list("title", flat=True)) == ["Comfortably Numb"]

    def test_invalid_part_then_400_and_nothing_staged(self):
        run_id = self.api_client.post(path=RUNS).data["run_id"]
        invalid = [
            b"not gzip",
            _gzip_ndjson([{**SONG, "musicbrainz_recording_id": None}]),
            _gzip_ndjson([{**SONG, "youtube_unplayable_reason": "bogus"}]),
            _gzip_ndjson([{**SONG, "title": "x" * (settings.TRACK_TITLE_LEN_MAX + 1)}]),
            _gzip_ndjson([{k: v for k, v in SONG.items() if k != "artist"}]),
            _gzip_ndjson([{**SONG, "first_release_year": "1979"}]),
            _gzip_ndjson([{**SONG, "first_release_year": True}]),
            _gzip_ndjson([{**SONG, "first_release_year": -1}]),
            _gzip_ndjson([{k: v for k, v in SONG.items() if k != "first_release_year"}]),
            gzip.compress(b"{not json\n"),
        ]

        codes = [self._upload(run_id, 0, body).status_code for body in invalid]

        assert codes == [status.HTTP_400_BAD_REQUEST] * len(invalid)
        assert not SongImportStaging.objects.exists()

    def test_empty_run_fails_and_keeps_tracks(self):
        self.model_fixture_factory.create_recording(title="Kept", genre=None)
        run_id = self.api_client.post(path=RUNS).data["run_id"]

        response = self.api_client.post(path=f"{RUNS}{run_id}/commit/")

        # Sync django-q re-raises the task's error into the request; the cluster records it as a failed task.
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert list(Recording.objects.values_list("title", flat=True)) == ["Kept"]
        assert not BulkImportRun.objects.exists()

    def test_tag_name_is_not_a_genre(self):
        self.model_fixture_factory.create_tag("Rock")

        assert self._sync([SONG]) == {"imported": 1, "skipped": 1}
        assert Recording.objects.get().genre is None

    def test_pipeline_commit_recorded_and_admin_not(self):
        self.model_fixture_factory.create_genre("Rock")
        unmatched = {**SONG, "musicbrainz_recording_id": OTHER_MBID, "genre_name": "Unknown"}

        self._sync([SONG, unmatched])
        assert not ImportRun.objects.exists()
        self._sync([SONG, unmatched], client=self.pipeline)

        assert list(ImportRun.objects.values_list("kind", "count", "skipped_count")) == [("songs", 2, 1)]

    def test_stale_essential_track_removed_from_genre_essentials(self):
        rock = self.model_fixture_factory.create_genre("Rock")
        stale = self.model_fixture_factory.create_recording(title="Stale", genre=rock, youtube_video_id="stalevideo1")
        rock.essential_tracks.add(stale)

        self._sync([SONG])

        assert not Recording.objects.filter(pk=stale.pk).exists()
        assert not rock.essential_tracks.exists()

    def test_artist_upserted_on_mbid_adopting_legacy_name_match_and_links_resynced(self):
        self.model_fixture_factory.create_genre("Rock")
        legacy = self.model_fixture_factory.create_artist("Pink Floyd")
        song = {**SONG, "artist_musicbrainz_id": ARTIST_MBID}

        self._sync([song])
        track = Recording.objects.get()
        assert [(a.pk, a.musicbrainz_artist_id) for a in track.artists.all()] == [(legacy.pk, uuid.UUID(ARTIST_MBID))]

        self._sync([{**song, "artist": "The Pink Floyd"}, {**SONG, "musicbrainz_recording_id": OTHER_MBID}])

        # Same MBID: the song keeps its artist whatever the credited name; no MBID: matched on name, MBID-less only.
        assert [a.pk for a in Recording.objects.get(pk=track.pk).artists.all()] == [legacy.pk]
        namesake = Recording.objects.exclude(pk=track.pk).get().artists.get()
        assert (namesake.name, namesake.musicbrainz_artist_id) == ("Pink Floyd", None)
        self._sync([{**song, "artist_musicbrainz_id": None, "artist": "Syd Barrett"}])
        assert [a.name for a in Recording.objects.get().artists.all()] == ["Syd Barrett"]
        assert Artist.objects.filter(pk=legacy.pk).exists()

    def test_artist_recording_count_tracks_playable_recordings(self):
        self.model_fixture_factory.create_genre("Rock")
        playable = {**SONG, "artist_musicbrainz_id": ARTIST_MBID}
        unplayable = {
            **playable,
            "musicbrainz_recording_id": OTHER_MBID,
            "youtube_video_id": None,
        }

        self._sync([playable, unplayable])
        assert Artist.objects.get(musicbrainz_artist_id=ARTIST_MBID).recording_count == 1

        self._sync([playable, {**unplayable, "youtube_video_id": "zzz123defgh"}])
        assert Artist.objects.get(musicbrainz_artist_id=ARTIST_MBID).recording_count == 2

        self._sync([{**unplayable, "youtube_video_id": "zzz123defgh"}])
        assert Artist.objects.get(musicbrainz_artist_id=ARTIST_MBID).recording_count == 1

        self._sync([{**playable, "artist_musicbrainz_id": None, "artist": "Syd Barrett"}])
        assert Artist.objects.get(musicbrainz_artist_id=ARTIST_MBID).recording_count == 0
