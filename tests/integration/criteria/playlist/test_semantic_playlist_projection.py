from django.db import transaction
from the_music_tree_genre_kit.criteria.track_playlist_rel.TrackPlaylistRel import TrackPlaylistRel
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution

from grow.genre_graph.service import song_genre
from grow.genre_music.membership import membership_bucket_counts, stored_membership_bucket_counts
from grow.model.playlist.children.criteria.genre.GenrePlaylist import GenrePlaylist
from grow.model.song.Song import Song
from tests.utils.AppTestCase import AppTestCase
from tests.utils.song_graph import install_song_graph


class TestSemanticPlaylistProjection(AppTestCase):
    def assert_projection(self):
        assert stored_membership_bucket_counts() == membership_bucket_counts()

    def rel_genres(self, song):
        return set(TrackPlaylistRel.objects.filter(track=song).values_list("genre_id", flat=True))

    def setUp(self):
        super().setUp()
        factory = self.model_fixture_factory
        self.legacy = factory.create_genre("Legacy")
        self.rock = factory.create_genre("Rock")
        self.jazz = factory.create_genre("Jazz")
        self.song = factory.create_song("Song", genre=self.legacy)

    def test_dataset_activation_resyncs_relations_and_buckets(self):
        install_song_graph({self.legacy: [], self.rock: [self.song], self.jazz: []})
        assert self.rel_genres(self.song) == {self.rock.pk}
        self.assert_projection()

    def _jazz_node(self):
        attribution = GenreGraphAttribution.objects.get(track_id=self.song.pk)
        return attribution, attribution.node.dataset.nodes.get(identity=f"LOCAL:{self.jazz.pk}")

    def test_raw_reassignment_and_clear_follow_the_view(self):
        install_song_graph({self.legacy: [], self.rock: [self.song], self.jazz: []})
        attribution, jazz_node = self._jazz_node()
        GenreGraphAttribution.objects.filter(pk=attribution.pk).update(node=jazz_node)
        assert self.rel_genres(self.song) == {self.jazz.pk}
        self.assert_projection()
        GenreGraphAttribution.objects.filter(pk=attribution.pk).delete()
        assert self.rel_genres(self.song) == {None}
        self.assert_projection()

    def test_rolled_back_reassignment_leaves_relations_and_buckets(self):
        install_song_graph({self.legacy: [], self.rock: [self.song], self.jazz: []})
        attribution, jazz_node = self._jazz_node()
        with transaction.atomic():
            GenreGraphAttribution.objects.filter(pk=attribution.pk).update(node=jazz_node)
            transaction.set_rollback(True)
        assert self.rel_genres(self.song) == {self.rock.pk}
        self.assert_projection()

    def test_column_edits_do_not_move_relations_under_a_dataset(self):
        install_song_graph({self.legacy: [], self.rock: [self.song], self.jazz: []})
        Song.objects.filter(pk=self.song.pk).update(genre=self.jazz)
        assert self.rel_genres(self.song) == {self.rock.pk}
        self.assert_projection()

    def test_record_semantic_genre_change_moves_playlist_membership(self):
        install_song_graph({self.legacy: [], self.rock: [], self.jazz: [self.song]})
        song = Song.objects.get(pk=self.song.pk)
        Song.objects.record_semantic_genre_change(song, old_genre=self.legacy)
        assert song_genre(song) == self.jazz
        playlists = set(TrackPlaylistRel.objects.filter(track=song).values_list("playlist_id", flat=True))
        assert playlists == {GenrePlaylist.objects.get(criteria=self.jazz).pk}
        assert self.rel_genres(song) == {self.jazz.pk}
        self.assert_projection()
