from django.db.models import Q

from grow.model.song.Fields import Fields

# Mirrored by TrackManager._is_playable, PLAYABLE in grow/track/bulk_import/merge.py and migration 0051.
PLAYABLE = Q(**{f"{Fields.YOUTUBE_VIDEO_ID}__isnull": False, "youtube_unplayable_reason__isnull": True})

# Songs whose YouTube policy cannot block any viewer. Their playability is decided by the partial index
# grow_song_open_playable_idx (migration 0116) alone, without reading the 4 GB heap; this predicate must match it.
OPEN_REGION = Q(youtube_region_restriction__isnull=True) | Q(youtube_region_restriction__mode="unrestricted")
OPEN_PLAYABLE = PLAYABLE & OPEN_REGION
