from typing import Any

import requests
from django.conf import settings

VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
TIMEOUT_SECONDS = 15


class YoutubeLookupError(RuntimeError):
    pass


def unplayable_reason(item: dict[str, Any] | None) -> str | None:
    """Same rules as the pipeline's `youtube_video_status`; keep the two in sync."""
    if item is None:
        return "not_found"
    status = item["status"]
    if not status["embeddable"]:
        return "not_embeddable"
    if status["privacyStatus"] == "private":
        return "private"
    if status["uploadStatus"] != "processed":
        return "not_processed"
    return None


def fetch_unplayable_reason(video_id: str) -> str | None:
    """Asks the YouTube Data API whether a video can be played; `None` means playable."""
    try:
        response = requests.get(
            VIDEOS_ENDPOINT,
            params={"part": "status", "id": video_id},
            headers={"X-goog-api-key": settings.YOUTUBE_API_KEY},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        items = response.json()["items"]
    except (requests.RequestException, ValueError, KeyError) as error:
        raise YoutubeLookupError(f"YouTube lookup failed for {video_id}") from error
    return unplayable_reason(next((item for item in items if item["id"] == video_id), None))
