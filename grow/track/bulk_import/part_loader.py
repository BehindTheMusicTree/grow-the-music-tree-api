import gzip
import json
import uuid
from typing import IO

from django.conf import settings
from django.db import connection, transaction
from rest_framework.exceptions import ValidationError
from the_music_tree_genre_kit.track.YoutubeUnplayableReason import YoutubeUnplayableReason

from grow.track.bulk_import.SongImportStaging import SongImportStaging

COLUMNS = ("musicbrainz_recording_id", "title", "artist", "youtube_video_id", "youtube_unplayable_reason", "genre_name")
REQUIRED = {"musicbrainz_recording_id", "title", "artist"}
MAX_LENGTHS = {
    "title": settings.TRACK_TITLE_LEN_MAX,
    "artist": settings.ARTIST_NAME_LEN_MAX,
    "youtube_video_id": settings.YOUTUBE_TRACK_VIDEO_ID_LEN_MAX,
    "genre_name": settings.CRITERIA_NAME_LEN_MAX,
}
REASONS = set(YoutubeUnplayableReason.values)


def _row(line_number: int, line: bytes) -> tuple:
    try:
        song = json.loads(line)
        uuid.UUID(song["musicbrainz_recording_id"])
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValidationError(f"line {line_number}: invalid song ({e})") from e
    for column in COLUMNS:
        value = song.get(column)
        if value is None:
            if column in REQUIRED:
                raise ValidationError(f"line {line_number}: {column} is required")
            continue
        if not isinstance(value, str) or value == "":
            raise ValidationError(f"line {line_number}: {column} must be a non-empty string")
        if len(value) > MAX_LENGTHS.get(column, len(value)):
            raise ValidationError(f"line {line_number}: {column} is longer than {MAX_LENGTHS[column]}")
    if song.get("youtube_unplayable_reason") not in REASONS | {None}:
        raise ValidationError(f"line {line_number}: unknown youtube_unplayable_reason")
    return (*(song.get(column) for column in COLUMNS),)


@transaction.atomic
def load_part(run_id: int, part: int, body: IO[bytes]) -> int:
    """Replaces part `part` of run `run_id` with the gzip NDJSON `body`, streamed into staging with `COPY`."""
    SongImportStaging.objects.filter(run_id=run_id, part=part).delete()
    count = 0
    with (
        connection.cursor() as cursor,
        cursor.copy(  # type: ignore[attr-defined]
            f"COPY {SongImportStaging._meta.db_table} (run_id, part, {', '.join(COLUMNS)}) FROM STDIN"
        ) as copy,
    ):
        try:
            for line_number, line in enumerate(gzip.GzipFile(fileobj=body), 1):
                if line.strip():
                    copy.write_row((run_id, part, *_row(line_number, line)))
                    count += 1
        except (OSError, EOFError) as e:
            raise ValidationError(f"body is not valid gzip ({e})") from e
    return count
