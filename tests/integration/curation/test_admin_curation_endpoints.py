import uuid as uuid_lib
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status

from grow.model.criteria.children.genre.Genre import Genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.recording.Recording import Recording
from grow.youtube import YoutubeLookupError
from tests.integration.permission.test_google_id_token_auth import VERIFY, VIEWER_CLAIMS
from tests.utils.AppTestCase import AppTestCase

FETCH = "grow.model.recording.RecordingCurationManager.fetch_unplayable_reason"
MB_ID = "11111111-1111-4111-8111-111111111111"


class TestCase(AppTestCase):
    def _rock(self) -> Genre:
        return self.model_fixture_factory.create_genre("Rock", wikidata_id="Q11399")

    def _rule(self, list_name: str) -> list[dict]:
        return [
            {**entry.values, "key": entry.key} for entry in CurationEntry.objects.filter(list_name=list_name, user=None)
        ]

    def _recording(self, title="Song", genre=None, mb_id=MB_ID) -> Recording:
        return self.model_fixture_factory.create_recording(title, genre, musicbrainz_recording_id=mb_id)

    def _assign(self, recordings, genre):
        return self.api_client.post(
            path=reverse("recording-assign-genre"),
            data={"recordings": [str(r.uuid) for r in recordings], "genre": str(genre.uuid) if genre else None},
            format="json",
        )

    def _forbidden_and_unauthorized(self, method: str, path: str, data=None):
        call = getattr(self.api_client, method)
        self.api_client.credentials()
        assert call(path=path, data=data, format="json").status_code == status.HTTP_401_UNAUTHORIZED
        self.api_client.credentials(HTTP_AUTHORIZATION="Bearer some-token")
        with patch(VERIFY, return_value=VIEWER_CLAIMS):
            assert call(path=path, data=data, format="json").status_code == status.HTTP_403_FORBIDDEN

    def test_assign_genre_then_rule_row_and_undo(self):
        rock = self._rock()
        recording = self._recording()

        response = self._assign([recording], rock)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["previous"] == [{"uuid": str(recording.uuid), "genre": None}]
        recording.refresh_from_db()
        assert recording.genre.pk == rock.pk
        assert recording.is_manually_edited
        [rule] = self._rule("recording_genre")
        assert rule["genre_item_id"] == "Q11399"
        assert rule["key"] == MB_ID

        undo = self._assign([recording], None)

        assert undo.status_code == status.HTTP_200_OK
        recording.refresh_from_db()
        assert recording.genre is None
        [rule] = self._rule("recording_genre")
        assert rule["genre_item_id"] == ""

    def test_assign_genre_batch_then_previous_restores_each(self):
        rock, jazz = self._rock(), self.model_fixture_factory.create_genre("Jazz", wikidata_id="Q8341")
        a = self._recording("A", rock)
        b = self._recording("B", None, "22222222-2222-4222-8222-222222222222")

        previous = self._assign([a, b], jazz).json()["previous"]

        assert previous == [
            {"uuid": str(a.uuid), "genre": str(rock.uuid)},
            {"uuid": str(b.uuid), "genre": None},
        ]
        self._assign([a], rock)
        a.refresh_from_db()
        assert a.genre.pk == rock.pk

    def test_assign_genre_without_musicbrainz_id_then_400_and_nothing_written(self):
        rock = self._rock()
        ok, bad = self._recording(), self._recording("Bad", None, None)

        response = self._assign([ok, bad], rock)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not CurationEntry.objects.filter(list_name="recording_genre").exists()
        ok.refresh_from_db()
        assert ok.genre is None

    def test_assign_genre_then_401_and_403(self):
        self._forbidden_and_unauthorized("post", reverse("recording-assign-genre"), {"recordings": [], "genre": None})

    def test_patch_video_then_rule_row_and_youtube_called(self):
        recording = self._recording(genre=self._rock())

        with patch(FETCH, return_value="not_embeddable") as fetch:
            response = self.api_client.patch(
                reverse("recording-detail", kwargs={"pk": recording.uuid}), {"youtubeVideoId": "abc"}, format="json"
            )

        assert response.status_code == status.HTTP_200_OK
        fetch.assert_called_once_with("abc")
        recording.refresh_from_db()
        assert (recording.youtube_video_id, recording.youtube_unplayable_reason) == ("abc", "not_embeddable")
        assert recording.is_manually_edited
        [rule] = self._rule("recording_youtube_video")
        assert rule["youtube_video_id"] == "abc"
        assert rule["unplayable_reason"] == ""

    def test_patch_explicit_reason_then_youtube_not_called(self):
        recording = self._recording(genre=self._rock())

        with patch(FETCH) as fetch:
            response = self.api_client.patch(
                reverse("recording-detail", kwargs={"pk": recording.uuid}),
                {"youtubeVideoId": "abc", "youtubeUnplayableReason": "private"},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        fetch.assert_not_called()
        recording.refresh_from_db()
        assert recording.youtube_unplayable_reason == "private"
        assert self._rule("recording_youtube_video")[0]["unplayable_reason"] == "private"

    def test_patch_video_null_then_cleared_without_lookup(self):
        recording = self._recording(genre=self._rock())

        with patch(FETCH) as fetch:
            response = self.api_client.patch(
                reverse("recording-detail", kwargs={"pk": recording.uuid}), {"youtubeVideoId": None}, format="json"
            )

        assert response.status_code == status.HTTP_200_OK
        fetch.assert_not_called()
        recording.refresh_from_db()
        assert recording.youtube_video_id is None

    def test_patch_when_youtube_down_then_502_and_nothing_written(self):
        recording = self._recording(genre=self._rock())

        with patch(FETCH, side_effect=YoutubeLookupError("down")):
            response = self.api_client.patch(
                reverse("recording-detail", kwargs={"pk": recording.uuid}), {"youtubeVideoId": "abc"}, format="json"
            )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert not CurationEntry.objects.filter(list_name="recording_youtube_video").exists()

    def test_patch_other_field_or_no_musicbrainz_id_then_400(self):
        recording = self._recording(genre=self._rock())
        bare = self._recording("Bare", None, None)
        url = reverse("recording-detail", kwargs={"pk": recording.uuid})

        assert self.api_client.patch(url, {"title": "x"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert (
            self.api_client.patch(url, {"youtubeVideoId": "abc", "title": "x"}, format="json").status_code
            == status.HTTP_400_BAD_REQUEST
        )
        with patch(FETCH, return_value=None):
            response = self.api_client.patch(
                reverse("recording-detail", kwargs={"pk": bare.uuid}), {"youtubeVideoId": "abc"}, format="json"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_then_401_and_403_and_put_still_405(self):
        recording = self._recording(genre=self._rock())
        url = reverse("recording-detail", kwargs={"pk": recording.uuid})
        self._forbidden_and_unauthorized("patch", url, {"youtubeVideoId": "abc"})
        self.api_client.credentials()
        assert self.api_client.put(url, {"title": "x"}, format="json").status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_search_then_genreless_filter_and_cursor(self):
        rock = self._rock()
        artist = self.model_fixture_factory.create_artist("Nirvana")
        loose = self._recording("Lithium", None)
        loose.artists.add(artist)
        self._recording("Lithium Tree", rock, "33333333-3333-4333-8333-333333333333")

        everything = self.api_client.get(reverse("recording-search"), {"q": "lithium"}).json()
        genreless = self.api_client.get(reverse("recording-search"), {"q": "nirvana", "genreless": "true"}).json()

        assert len(everything["results"]) == 2
        assert [r["uuid"] for r in genreless["results"]] == [str(loose.uuid)]
        assert genreless["next"] is None

    def test_search_cursor_then_pages(self):
        for i in range(51):
            self.model_fixture_factory.create_recording(f"Bulk {i}", None)

        first = self.api_client.get(reverse("recording-search"), {"genreless": "true"}).json()
        second = self.api_client.get(reverse("recording-search"), {"genreless": "true", "cursor": first["next"]}).json()

        assert len(first["results"]) == 50
        assert len(second["results"]) == 1
        assert second["next"] is None

    def test_search_then_401_and_403(self):
        self._forbidden_and_unauthorized("get", reverse("recording-search"))

    def test_link_suggestions_then_sorted_by_shared_artists(self):
        rock = self._rock()
        a1, a2 = self.model_fixture_factory.create_artist("A1"), self.model_fixture_factory.create_artist("A2")
        known = self._recording("Known", rock)
        known.artists.add(a1, a2)
        one = self._recording("One", None, "44444444-4444-4444-8444-444444444444")
        one.artists.add(a1)
        two = self._recording("Two", None, "55555555-5555-4555-8555-555555555555")
        two.artists.add(a1, a2)
        stranger = self._recording("Stranger", None, "66666666-6666-4666-8666-666666666666")
        stranger.artists.add(self.model_fixture_factory.create_artist("Other"))

        response = self.api_client.get(reverse("genre-link-suggestions", kwargs={"pk": rock.uuid}))

        assert response.status_code == status.HTTP_200_OK
        assert [(r["uuid"], r["sharedArtists"]) for r in response.json()] == [(str(two.uuid), 2), (str(one.uuid), 1)]

    def test_link_suggestions_then_401_and_403(self):
        self._forbidden_and_unauthorized("get", reverse("genre-link-suggestions", kwargs={"pk": uuid_lib.uuid4()}))

    def _secondary(self, method: str, genre: Genre, parent: Genre):
        url = reverse("genre-secondary-parent", kwargs={"pk": genre.uuid, "parent_uuid": parent.uuid})
        return getattr(self.api_client, method)(url)

    def test_secondary_parent_add_then_remove(self):
        root = self.model_fixture_factory.create_genre("Music", wikidata_id="Q638")
        genre = self.model_fixture_factory.create_genre("Grunge", wikidata_id="Q11366", parent=root)
        other = self.model_fixture_factory.create_genre("Punk", wikidata_id="Q3071", parent=root)

        response = self._secondary("post", genre, other)

        assert response.status_code == status.HTTP_200_OK
        assert [g.pk for g in genre.secondary_parents.all()] == [other.pk]
        [rule] = self._rule("secondary_parents")
        assert rule["action"] == "add"
        genre.refresh_from_db()
        assert genre.is_manually_edited

        undo = self._secondary("delete", genre, other)

        assert undo.status_code == status.HTTP_200_OK
        assert not genre.secondary_parents.exists()
        [rule] = self._rule("secondary_parents")
        assert rule["action"] == "remove"

    def test_secondary_parent_invalid_then_400(self):
        root = self.model_fixture_factory.create_genre("Music", wikidata_id="Q638")
        genre = self.model_fixture_factory.create_genre("Grunge", wikidata_id="Q11366", parent=root)
        local = self.model_fixture_factory.create_genre("Local")

        assert self._secondary("post", genre, genre).status_code == status.HTTP_400_BAD_REQUEST
        assert self._secondary("post", genre, root).status_code == status.HTTP_400_BAD_REQUEST
        assert self._secondary("post", genre, local).status_code == status.HTTP_400_BAD_REQUEST
        assert not CurationEntry.objects.filter(list_name="secondary_parents").exists()

    def test_secondary_parent_then_401_and_403(self):
        url = reverse("genre-secondary-parent", kwargs={"pk": uuid_lib.uuid4(), "parent_uuid": uuid_lib.uuid4()})
        self._forbidden_and_unauthorized("post", url)
        self._forbidden_and_unauthorized("delete", url)

    def test_alias_of_then_rule_and_everything_moved(self):
        root = self.model_fixture_factory.create_genre("Music", wikidata_id="Q638")
        target = self.model_fixture_factory.create_genre("Alternative rock", wikidata_id="Q11366", parent=root)
        source = self.model_fixture_factory.create_genre("alt rock", parent=root)
        child = self.model_fixture_factory.create_genre("Child", parent=source)
        recording = self._recording("Song", source)
        source.essential_tracks.add(recording)
        url = reverse("genre-alias-of", kwargs={"pk": source.uuid})

        preview = self.api_client.get(
            reverse("genre-alias-of-preview", kwargs={"pk": source.uuid}), {"target": str(target.uuid)}
        )
        response = self.api_client.post(url, {"target": str(target.uuid)}, format="json")

        assert preview.json() == {"recordings": 1, "essentialTracks": 1, "children": 1}
        assert response.status_code == status.HTTP_200_OK
        assert not Genre.objects.filter(pk=source.pk).exists()
        recording.refresh_from_db()
        child.refresh_from_db()
        assert recording.genre.pk == target.pk
        assert child.parent.pk == target.pk
        assert list(target.essential_tracks.all()) == [Recording.objects.get(pk=recording.pk)]
        [rule] = self._rule("genre_alias")
        assert (rule["key"], rule["wikidata_genre_name"]) == ("alt rock", "Alternative rock")

    def test_alias_of_not_allowed_then_400(self):
        wikidata = self.model_fixture_factory.create_genre("Rock", wikidata_id="Q11399")
        other = self.model_fixture_factory.create_genre("Jazz", wikidata_id="Q8341")
        local_a = self.model_fixture_factory.create_genre("Local A")
        local_b = self.model_fixture_factory.create_genre("Local B")

        for source, target in ((wikidata, other), (local_a, local_b)):
            url = reverse("genre-alias-of", kwargs={"pk": source.uuid})
            response = self.api_client.post(url, {"target": str(target.uuid)}, format="json")
            preview = self.api_client.get(
                reverse("genre-alias-of-preview", kwargs={"pk": source.uuid}), {"target": str(target.uuid)}
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert preview.status_code == status.HTTP_400_BAD_REQUEST
        assert not CurationEntry.objects.filter(list_name="genre_alias").exists()
        assert Genre.objects.filter(pk=wikidata.pk).exists()

    def test_alias_of_then_401_and_403(self):
        pk = uuid_lib.uuid4()
        self._forbidden_and_unauthorized("post", reverse("genre-alias-of", kwargs={"pk": pk}), {"target": str(pk)})
        self._forbidden_and_unauthorized("get", reverse("genre-alias-of-preview", kwargs={"pk": pk}))

    def test_put_summary_and_essential_tracks_then_rules(self):
        genre = self._rock()
        a = self._recording("A", genre)
        b = self._recording("B", genre, "77777777-7777-4777-8777-777777777777")
        url = reverse("genre-detail", kwargs={"pk": genre.uuid})

        response = self.api_client.put(
            url, {"summary": "Loud.", "essentialTracks": [str(b.uuid), str(a.uuid)]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        genre.refresh_from_db()
        assert genre.summary == "Loud."
        assert genre.is_manually_edited
        assert {t.pk for t in genre.essential_tracks.all()} == {a.pk, b.pk}
        [summary] = self._rule("summary_overrides")
        assert summary["summary"] == "Loud."
        positions = {r["key"].split("\t")[1]: r["position"] for r in self._rule("essential_tracks")}
        assert positions == {str(b.musicbrainz_recording_id): "1", str(a.musicbrainz_recording_id): "2"}

        self.api_client.put(url, {"essentialTracks": [str(a.uuid)]}, format="json")

        assert [r["key"].split("\t")[1] for r in self._rule("essential_tracks")] == [str(a.musicbrainz_recording_id)]

    def test_put_essential_track_without_musicbrainz_id_then_400(self):
        genre = self._rock()
        bare = self._recording("Bare", genre, None)

        response = self.api_client.put(
            reverse("genre-detail", kwargs={"pk": genre.uuid}), {"essentialTracks": [str(bare.uuid)]}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not genre.essential_tracks.exists()
