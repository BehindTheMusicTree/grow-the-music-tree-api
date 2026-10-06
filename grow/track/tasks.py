from typing import Any

from django.contrib.auth import get_user_model

from grow.model.import_run.ImportRun import ImportRun
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack


def run_import_seed_songs(user_id: int | None, validated_data: list[dict[str, Any]], record: bool) -> dict[str, int]:
    user = get_user_model().objects.get(pk=user_id) if user_id is not None else None
    result = YoutubeTrack.objects.import_seed_songs(user, validated_data)
    if record:
        ImportRun.objects.create(kind=ImportRun.Kind.SONGS, count=result["imported"], skipped_count=result["skipped"])
    return result
