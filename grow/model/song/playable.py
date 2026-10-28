from django.db.models import Q

from grow.model.song.Fields import Fields

# Mirrored by TrackManager._is_playable, PLAYABLE in grow/track/bulk_import/merge.py and migration 0051.
PLAYABLE = Q(**{f"{Fields.YOUTUBE_VIDEO_ID}__isnull": False, "youtube_unplayable_reason__isnull": True})
