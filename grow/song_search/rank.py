"""
A song's static search rank, stored in `grow_song_search.rank_score` and computed from the song (`s`) and its track
(`t`) rows. Having a genre weighs most, then being playable, then popularity: MusicBrainz recordings grouped into the
song (live versions, remasters, compilations) on a log scale, and YouTube views on a log10 scale, each capped. The caps
keep one huge number from drowning the other signals.
"""

GENRE_WEIGHT = 1000
PLAYABLE_WEIGHT = 500
RECORDING_COUNT_FACTOR = 120
RECORDING_COUNT_CAP = 899
VIEW_COUNT_FACTOR = 50
VIEW_COUNT_CAP = 499

# Same predicate as TrackManager._is_playable and PLAYABLE in grow/model/song/playable.py.
PLAYABLE_SQL = "(s.youtube_video_id IS NOT NULL AND s.youtube_unplayable_reason IS NULL)"
HAS_GENRE_SQL = "(t.genre_id IS NOT NULL)"

RANK_SCORE_SQL = f"""(
    CASE WHEN {HAS_GENRE_SQL} THEN {GENRE_WEIGHT} ELSE 0 END
    + CASE WHEN {PLAYABLE_SQL} THEN {PLAYABLE_WEIGHT} ELSE 0 END
    + least(round(ln(greatest(coalesce(s.recording_count, 1), 1)::float8) * {RECORDING_COUNT_FACTOR}),
        {RECORDING_COUNT_CAP})
    + least(round(log(coalesce(s.youtube_view_count, 0)::float8 + 1) * {VIEW_COUNT_FACTOR}), {VIEW_COUNT_CAP})
)::int"""
