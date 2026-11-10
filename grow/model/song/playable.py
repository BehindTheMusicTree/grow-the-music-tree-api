from django.db.models import Q

from grow.model.song.Fields import Fields

# Mirrored by TrackManager._is_playable, PLAYABLE in grow/track/bulk_import/merge.py and migration 0051.
PLAYABLE = Q(**{f"{Fields.YOUTUBE_VIDEO_ID}__isnull": False, "youtube_unplayable_reason__isnull": True})

# Songs whose policy can block a viewer ("allowed" and "blocked" lists; "unrestricted" and NULL never do). They are
# about 0.4% of grow_song, so the partial index grow_song_restricted_idx (migration 0117) holds only them and
# answers a region probe from cache; this predicate must match its condition.
RESTRICTED_POLICY = Q(youtube_region_restriction__mode="allowed") | Q(youtube_region_restriction__mode="blocked")
