from typing import Any

from django.contrib.auth import get_user_model

from grow.model.youtube_track.YoutubeTrack import YoutubeTrack


def run_import_seed_songs(user_id: int, validated_data: list[dict[str, Any]]) -> dict[str, int]:
    user = get_user_model().objects.get(pk=user_id)
    return YoutubeTrack.objects.import_seed_songs(user, validated_data)
