from typing import Any

from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField

from grow.model.song.Song import Song


class EssentialSongsInputMixin(serializers.Serializer):
    essential_songs = PrimaryKeyRelatedField(queryset=Song.objects.all(), many=True, required=False)
    # Deprecated alias of `essential_songs`, accepted for one release; `essential_songs` wins.
    essential_tracks = PrimaryKeyRelatedField(queryset=Song.objects.all(), many=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        legacy = attrs.pop("essential_tracks", None)
        if legacy is not None:
            attrs.setdefault("essential_songs", legacy)
        return super().validate(attrs)
