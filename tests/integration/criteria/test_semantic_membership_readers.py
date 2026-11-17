import pytest
from django.db.models import Count
from the_music_tree_genre_kit.genre_graph.models import GenreGraphAttribution

from grow.genre_music.artist import artist_exact_counts
from grow.model.song.Song import Song
from grow.serializer.model.artist.simple import playable_tracks_count, tracks_count
from grow.serializer.model.song.output.without_playlists import SongWithoutPlaylistsSerializer
from grow.serializer.model.song.search import SongSearchResultSerializer
from tests.utils.ModelFixtureFactory import ModelFixtureFactory
from tests.utils.song_graph import install_song_graph

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("serializer_class", [SongWithoutPlaylistsSerializer, SongSearchResultSerializer])
def test_song_serialization_uses_effective_nullable_genre(serializer_class):
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    assigned = factory.create_genre("Assigned")
    song = factory.create_song("Song", legacy)
    install_song_graph({legacy: [], assigned: [song]})
    song = Song.objects.select_related("song_membership__genre").get(pk=song.pk)
    assert str(serializer_class(song).data["genre"]["uuid"]) == str(assigned.pk)
    GenreGraphAttribution.objects.filter(track_id=song.pk).delete()
    song = Song.objects.select_related("song_membership__genre").get(pk=song.pk)
    assert serializer_class(song).data["genre"] is None


def test_artist_buckets_and_annotations_follow_membership_not_legacy_genre():
    factory = ModelFixtureFactory(None)
    legacy = factory.create_genre("Legacy")
    assigned = factory.create_genre("Assigned")
    artist = factory.create_artist("Artist")
    song = factory.create_song("Song", legacy, artists=[artist])
    install_song_graph({legacy: [], assigned: [song]})
    assert artist_exact_counts(artist.pk) == {assigned.pk: 1}
    annotated = type(artist).objects.annotate(total=tracks_count(), playable=playable_tracks_count()).get(pk=artist.pk)
    assert annotated.total == 1
    assert annotated.playable == 1
    GenreGraphAttribution.objects.filter(track_id=song.pk).delete()
    assert artist_exact_counts(artist.pk) == {None: 1}
    annotated = type(artist).objects.annotate(total=tracks_count(), playable=playable_tracks_count()).get(pk=artist.pk)
    assert annotated.total == 0
    assert annotated.playable == 0
    assert Song.objects.aggregate(total=Count("pk"))["total"] == 1
