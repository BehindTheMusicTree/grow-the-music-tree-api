from django.db.models import Prefetch
from rest_framework import serializers

from grow.model.criteria.children.genre.GenreEssentialSong import GenreEssentialSong
from grow.serializer.model.track.output.simple.simple_without_album_and_genre import (
    TrackWithoutAlbumPlaylistGenreSerializer,
)


def essential_song_rows_prefetch(genre_path: str) -> Prefetch:
    """Position-ordered through rows (Meta.ordering) with their songs and artists, read by `get_essential_songs`."""
    return Prefetch(
        f"{genre_path}__genreessentialsong_set",
        GenreEssentialSong.objects.select_related("song").prefetch_related("song__artists"),
    )


class CriteriaEssentialSongsSerializerMixin:
    """
    Resolves `essential_songs` for a serializer whose `Meta.model` is the shared base
    `Criteria` table rather than the concrete `Genre` MTI subtype -- `essential_songs`
    only exists as a field on `Genre`, reached from a base `Criteria` instance via the
    reverse `genre` one-to-one accessor. Mirrors the kit's `CriteriaSideSerializerMixin`.

    Safe for non-genre criteria (e.g. `Tag`): Django's `RelatedObjectDoesNotExist`
    subclasses both `Genre.DoesNotExist` and `AttributeError`, so
    `getattr(obj, "genre", None)` returns `None` rather than raising.
    """

    essential_songs = serializers.SerializerMethodField()
    _declared_fields = {"essential_songs": essential_songs}

    def get_essential_songs(self, obj) -> list[dict]:
        genre = getattr(obj, "genre", None)
        if not genre:
            return []
        songs = [row.song for row in genre.genreessentialsong_set.all()]
        return TrackWithoutAlbumPlaylistGenreSerializer(songs, many=True, context=self.context).data
