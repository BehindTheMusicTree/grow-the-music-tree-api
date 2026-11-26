from django.urls import reverse
from rest_framework import status
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution, GenreGraphEvidence

from grow.genre_graph.service import song_attribution_state, song_genre
from grow.model.curation.CurationEntry import CurationEntry
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase
from tests.utils.song_graph import install_song_graph

MB_ID = "11111111-1111-4111-8111-111111111111"


class TestCase(AppTestCase):
    def _assign(self, songs, genre):
        return self.api_client.post(
            path=reverse("song-assign-genre"),
            data={"songs": [str(s.uuid) for s in songs], "genre": str(genre.uuid) if genre else None},
            format="json",
        )

    def _setup(self):
        rock = self.model_fixture_factory.create_genre("Rock", wikidata_id="Q11399")
        jazz = self.model_fixture_factory.create_genre("Jazz", wikidata_id="Q8341")
        song = self.model_fixture_factory.create_song("Song", None, musicbrainz_recording_id=MB_ID)
        return rock, jazz, song

    def test_with_dataset_then_attribution_written_and_legacy_column_untouched(self):
        rock, jazz, song = self._setup()
        install_song_graph({rock: [], jazz: []})

        response = self._assign([song], rock)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["previous"] == [{"uuid": str(song.uuid), "genre": None, "undoable": False}]
        assert song_genre(Song.objects.get(pk=song.pk)) == rock
        assert Song.objects.get(pk=song.pk).genre_id is None

    def test_with_dataset_then_evidence_equals_the_rule_provenance(self):
        rock, jazz, song = self._setup()
        install_song_graph({rock: [], jazz: []})

        self._assign([song], rock)

        rule = CurationEntry.objects.get(list_name="song_genre", key=MB_ID, user=None)
        evidence = GenreGraphEvidence.objects.get(decision_id=rule.values["decision_id"])
        assert (evidence.source, evidence.rationale) == (rule.values["decision_source"], rule.reason)

    def test_with_dataset_then_undo_restores_the_rule_with_its_provenance(self):
        rock, jazz, song = self._setup()
        install_song_graph({rock: [], jazz: []})
        self._assign([song], rock)
        before = CurationEntry.objects.get(list_name="song_genre", key=MB_ID, user=None).row

        undo = self.api_client.post(
            path=reverse("song-undo-assign-genre"),
            data={"undoToken": self._assign([song], jazz).json()["undoToken"]},
            format="json",
        )

        assert undo.status_code == status.HTTP_204_NO_CONTENT
        assert CurationEntry.objects.get(list_name="song_genre", key=MB_ID, user=None).row == before

    def test_with_dataset_then_move_reports_previous_and_replaces_attribution(self):
        rock, jazz, song = self._setup()
        install_song_graph({rock: [song], jazz: []})

        response = self._assign([song], jazz)

        assert response.json()["previous"] == [{"uuid": str(song.uuid), "genre": str(rock.uuid), "undoable": False}]
        assert song_genre(song) == jazz
        assert GenreGraphAttribution.objects.filter(track_id=song.pk).count() == 1

    def test_with_dataset_then_unlink_removes_attribution_and_undo_restores(self):
        rock, jazz, song = self._setup()
        install_song_graph({rock: [song], jazz: []})

        assert self._assign([song], None).status_code == status.HTTP_200_OK
        assert song_genre(song) is None
        assert not GenreGraphAttribution.objects.filter(track_id=song.pk).exists()

        assert self._assign([song], rock).status_code == status.HTTP_200_OK
        assert song_genre(song) == rock

    def test_with_dataset_then_genre_without_active_node_is_rejected_and_nothing_changes(self):
        rock, jazz, song = self._setup()
        install_song_graph({rock: []})

        response = self._assign([song], jazz)

        assert response.status_code >= status.HTTP_400_BAD_REQUEST
        assert song_genre(song) is None
        assert not GenreGraphAttribution.objects.filter(track_id=song.pk).exists()

    def test_without_dataset_then_legacy_column_is_written(self):
        rock, _, song = self._setup()

        assert self._assign([song], rock).status_code == status.HTTP_200_OK
        assert Song.objects.get(pk=song.pk).genre_id == rock.pk
        assert song_genre(song) == rock

    def test_with_dataset_then_undo_restores_original_attribution_and_provenance(self):
        rock, jazz, song = self._setup()
        install_song_graph({rock: [song], jazz: []})
        before = song_attribution_state(song)

        response = self._assign([song], jazz)
        assert song_genre(song) == jazz

        undo = self.api_client.post(
            path=reverse("song-undo-assign-genre"), data={"undoToken": response.json()["undoToken"]}, format="json"
        )

        assert undo.status_code == status.HTTP_204_NO_CONTENT
        assert song_genre(song) == rock
        assert song_attribution_state(song)[0] == before[0]

    def test_with_dataset_then_undo_after_another_write_is_409_for_the_whole_batch(self):
        rock, jazz, song = self._setup()
        other = self.model_fixture_factory.create_song(
            "Other", None, musicbrainz_recording_id="22222222-2222-4222-8222-222222222222"
        )
        install_song_graph({rock: [], jazz: []})
        response = self._assign([song, other], rock)
        self._assign([other], jazz)

        undo = self.api_client.post(
            path=reverse("song-undo-assign-genre"), data={"undoToken": response.json()["undoToken"]}, format="json"
        )

        assert undo.status_code == status.HTTP_409_CONFLICT
        assert song_genre(song) == rock
        assert song_genre(other) == jazz
