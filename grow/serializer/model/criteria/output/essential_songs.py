from rest_framework import serializers

from grow.serializer.model.track.output.simple.simple_without_album_and_genre import (
    TrackWithoutAlbumPlaylistGenreSerializer,
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
    # Deprecated duplicate of `essential_songs`, kept for one release.
    essential_tracks = serializers.SerializerMethodField()
    _declared_fields = {"essential_songs": essential_songs, "essential_tracks": essential_tracks}

    def get_essential_songs(self, obj) -> list[dict]:
        genre = getattr(obj, "genre", None)
        if not genre:
            return []
        return TrackWithoutAlbumPlaylistGenreSerializer(
            genre.essential_songs.all(), many=True, context=self.context
        ).data

    def get_essential_tracks(self, obj) -> list[dict]:
        return self.get_essential_songs(obj)
