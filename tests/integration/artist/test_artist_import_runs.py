import gzip
import io
import json
import resource
import sys
from unittest import mock

import pytest
from django.conf import settings
from django.db import connection
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from grow.artist.bulk_import.ArtistImportStaging import ArtistImportStaging
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.model.album.Album import Album
from grow.model.artist.Artist import Artist
from grow.model.artist_link.ArtistLink import ArtistLink
from grow.model.artist_membership.ArtistMembership import ArtistMembership
from grow.model.import_run.ImportRun import ImportRun
from tests.utils.AppTestCase import AppTestCase

BAND = "83d91898-7763-47d7-b03b-b92132375c47"
MEMBER = "e8ff7d2c-9c55-4e2d-8a5e-0e2f1e0d1c11"
RELEASE_GROUP = "f5093c06-23e3-404f-aeaa-40f72885ee3a"
ARTIST = {
    "musicbrainz_artist_id": BAND,
    "name": "Pink Floyd",
    "type": "group",
    "country": "GB",
    "begin_year": 1965,
    "end_year": 2014,
    "ended": True,
    "members": [
        {"musicbrainz_artist_id": MEMBER, "begin_year": 1965, "end_year": 1985, "ended": True, "roles": ["bass guitar"]}
    ],
    "links": [{"kind": "official", "url": "https://www.pinkfloyd.com/"}],
    "release_groups": [
        {
            "musicbrainz_release_group_id": RELEASE_GROUP,
            "title": "The Wall",
            "primary_type": "Album",
            "secondary_types": [],
            "first_release_year": 1979,
        }
    ],
}
PERSON = {
    **ARTIST,
    "musicbrainz_artist_id": MEMBER,
    "name": "Roger Waters",
    "type": "person",
    "end_year": None,
    "ended": False,
    "members": [],
    "links": [],
}
RUNS = reverse("artist-list") + "import-runs/"


def _gzip_ndjson(artists: list[dict]) -> bytes:
    return gzip.compress("".join(json.dumps(artist) + "\n" for artist in artists).encode())


class TestImportRunProtocol(AppTestCase):
    def test_create_run_abandons_only_uncommitted_artist_runs(self):
        songs_run = BulkImportRun.objects.create(kind=ImportRun.Kind.SONGS)
        first = self.api_client.post(path=RUNS).data["run_id"]

        second = self.api_client.post(path=RUNS)

        assert second.status_code == status.HTTP_201_CREATED
        assert sorted(BulkImportRun.objects.values_list("pk", flat=True)) == [songs_run.pk, second.data["run_id"]]
        assert first != second.data["run_id"]

    def test_commit_other_kind_run_then_404(self):
        songs_run = BulkImportRun.objects.create(kind=ImportRun.Kind.SONGS)

        assert self.api_client.post(path=f"{RUNS}{songs_run.pk}/commit/").status_code == status.HTTP_404_NOT_FOUND

    def test_status_reports_pending_for_unknown_task(self):
        response = self.api_client.get(path=reverse("artist-list") + "import/does-not-exist/status/")

        assert response.data["status"] == "pending"

    def test_viewer_cannot_create_run(self):
        self.api_client.credentials()

        assert self.api_client.post(path=RUNS).status_code == status.HTTP_401_UNAUTHORIZED


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

    def _sync(self, *parts: list[dict], client=None) -> dict:
        client = client or self.api_client
        run_id = client.post(path=RUNS).data["run_id"]
        for part, artists in enumerate(parts):
            response = self._upload(run_id, part, _gzip_ndjson(artists), client)
            assert response.status_code == status.HTTP_200_OK, response.content
            assert response.data["count"] == len(artists)
        response = client.post(path=f"{RUNS}{run_id}/commit/")
        assert response.status_code == status.HTTP_202_ACCEPTED
        task = self.api_client.get(path=reverse("artist-list") + f"import/{response.data['task_id']}/status/")
        assert task.data["status"] == "success", task.data
        return task.data["result"]

    def test_import_creates_artists_memberships_links_and_release_groups(self):
        assert self._sync([ARTIST, PERSON]) == {"imported": 2, "skipped": 0}

        band = Artist.objects.get(musicbrainz_artist_id=BAND)
        assert (band.name, band.type, band.country, band.begin_year, band.end_year, band.ended) == (
            "Pink Floyd",
            "group",
            "GB",
            1965,
            2014,
            True,
        )
        membership = ArtistMembership.objects.get()
        assert (membership.group, membership.member.name, membership.ended, membership.roles) == (
            band,
            "Roger Waters",
            True,
            ["bass guitar"],
        )
        assert list(band.links.values_list("kind", "url")) == [("official", "https://www.pinkfloyd.com/")]
        album = Album.objects.get()
        assert (album.name, album.year, album.primary_type, album.secondary_types) == ("The Wall", "1979", "Album", [])
        assert {a.name for a in album.album_artists.all()} == {"Pink Floyd", "Roger Waters"}
        assert not ArtistImportStaging.objects.exists() and not BulkImportRun.objects.exists()

    def test_long_release_group_title_imported_verbatim(self):
        title = "x" * 890
        self._sync([{**ARTIST, "release_groups": [{**ARTIST["release_groups"][0], "title": title}]}])

        assert Album.objects.get().name == title

    def test_reimport_updates_in_place_and_resyncs_links(self):
        self._sync([ARTIST, PERSON])
        band_uuid = Artist.objects.get(musicbrainz_artist_id=BAND).uuid
        renamed = {**ARTIST, "name": "The Pink Floyd", "links": [{"kind": "wikidata", "url": "https://wd/Q2306"}]}

        self._sync([renamed, {**PERSON, "release_groups": []}])

        band = Artist.objects.get(musicbrainz_artist_id=BAND)
        assert (band.uuid, band.name) == (band_uuid, "The Pink Floyd")
        assert list(ArtistLink.objects.values_list("kind", flat=True)) == ["wikidata"]
        assert [a.name for a in Album.objects.get().album_artists.all()] == ["The Pink Floyd"]

    def test_reuploaded_part_replaces_its_rows(self):
        run_id = self.api_client.post(path=RUNS).data["run_id"]
        self._upload(run_id, 0, _gzip_ndjson([{**ARTIST, "name": "First"}]))

        assert self._upload(run_id, 0, _gzip_ndjson([ARTIST])).data["count"] == 1

        assert [row["name"] for row in ArtistImportStaging.objects.values_list("data", flat=True)] == ["Pink Floyd"]

    def test_part_upload_memory_does_not_grow_with_part_size(self):
        """A server slower than the client must not make the worker buffer the part (prod OOM on 250k-row parts)."""

        def part(rows: int) -> bytes:
            line = (json.dumps({**ARTIST, "release_groups": ARTIST["release_groups"] * 40}) + "\n").encode()
            body = io.BytesIO()
            with gzip.GzipFile(fileobj=body, mode="wb") as gz:
                for _ in range(rows):
                    gz.write(line)
            return body.getvalue()

        def peak_rss_mb() -> float:
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e6 if sys.platform == "darwin" else 1e3)

        small, large = part(500), part(10_000)  # ~3 MB and ~50 MB uncompressed
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE FUNCTION slow_staging() RETURNS trigger AS $$ BEGIN PERFORM pg_sleep(0.0002); RETURN NEW; END "
                "$$ LANGUAGE plpgsql"
            )
            cursor.execute(
                "CREATE TRIGGER slow_staging BEFORE INSERT ON grow_artist_import_staging "
                "FOR EACH ROW EXECUTE FUNCTION slow_staging()"
            )
        run_id = self.api_client.post(path=RUNS).data["run_id"]
        # psycopg's Linux default, so the check also bites on macOS.
        with mock.patch("psycopg._copy.PREFER_FLUSH", False):
            assert self._upload(run_id, 0, small).data["count"] == 500
            # ponytail: ru_maxrss is a process-wide high-water mark, so an earlier peak can mask growth here.
            baseline = peak_rss_mb()
            assert self._upload(run_id, 1, large).data["count"] == 10_000

        assert peak_rss_mb() - baseline < 10

    def test_artist_missing_from_run_deleted_unless_credited(self):
        factory = self.model_fixture_factory
        credited = factory.create_artist("Credited")
        factory.create_recording(title="Song", genre=None, artists=[credited])
        factory.create_artist("Stale")
        self._sync([ARTIST, PERSON])

        self._sync([{**PERSON, "release_groups": []}])

        assert sorted(Artist.objects.values_list("_name", flat=True)) == ["Credited", "Roger Waters"]
        assert not ArtistMembership.objects.exists() and not ArtistLink.objects.exists()
        assert not Album.objects.exists()

    def test_invalid_part_then_400_and_nothing_staged(self):
        run_id = self.api_client.post(path=RUNS).data["run_id"]
        invalid = [
            b"not gzip",
            _gzip_ndjson([{**ARTIST, "musicbrainz_artist_id": "nope"}]),
            _gzip_ndjson([{**ARTIST, "type": "band"}]),
            _gzip_ndjson([{**ARTIST, "links": [{"kind": "myspace", "url": "https://myspace.com"}]}]),
            _gzip_ndjson([{**ARTIST, "release_groups": [{**ARTIST["release_groups"][0], "title": ""}]}]),
            _gzip_ndjson([{**ARTIST, "release_groups": [{**ARTIST["release_groups"][0], "title": "x" * 2049}]}]),
        ]

        codes = [self._upload(run_id, 0, body).status_code for body in invalid]

        assert codes == [status.HTTP_400_BAD_REQUEST] * len(invalid)
        assert not ArtistImportStaging.objects.exists()

    def test_empty_run_fails_and_keeps_artists(self):
        self.model_fixture_factory.create_artist("Kept")
        run_id = self.api_client.post(path=RUNS).data["run_id"]

        response = self.api_client.post(path=f"{RUNS}{run_id}/commit/")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert list(Artist.objects.values_list("_name", flat=True)) == ["Kept"]
        assert not BulkImportRun.objects.exists()

    def test_pipeline_commit_recorded_and_admin_not(self):
        self._sync([ARTIST])
        assert not ImportRun.objects.exists()

        self._sync([ARTIST], client=self.pipeline)

        assert list(ImportRun.objects.values_list("kind", "count", "skipped_count")) == [("artists", 1, 0)]
