from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction

from grow.model.history.HistoryAction import HistoryAction
from grow.model.import_run.ImportRun import ImportRun
from grow.model.youtube_track.YoutubeTrack import YoutubeTrack
from grow.track.bulk_import.SongImportRun import SongImportRun
from grow.track.bulk_import.SongImportStaging import SongImportStaging

TEMP_TABLES = (
    "song_import, genre_playlist, track_genre_change, desired_rel, new_rel, touched_playlist, stale, stale_artist"
)

# One song per MBID (a re-uploaded part's latest copy wins), matched to the owner's track by MBID, else a legacy
# MBID-less track adopted by video id (one song per video), else a new track id.
SONG_IMPORT = """
CREATE TEMP TABLE song_import AS
WITH staged AS (
    SELECT DISTINCT ON (musicbrainz_recording_id)
        musicbrainz_recording_id AS mbid, title, artist, youtube_video_id, youtube_unplayable_reason, genre_name
    FROM grow_song_import_staging WHERE run_id = %(run)s
    ORDER BY musicbrainz_recording_id, part DESC
), owned AS (
    SELECT y.track_id, y.musicbrainz_recording_id, y.youtube_video_id, y.is_manually_edited
    FROM grow_youtube_track y JOIN the_music_tree_genre_kit_track t ON t.uuid = y.track_id
    WHERE t.user_id IS NOT DISTINCT FROM %(user)s
), matched AS (
    SELECT s.*, o.track_id, o.is_manually_edited FROM staged s LEFT JOIN owned o ON o.musicbrainz_recording_id = s.mbid
), legacy AS (
    SELECT DISTINCT ON (youtube_video_id) track_id, youtube_video_id, is_manually_edited FROM owned
    WHERE musicbrainz_recording_id IS NULL AND youtube_video_id IS NOT NULL ORDER BY youtube_video_id, track_id
), candidate AS (
    SELECT DISTINCT ON (youtube_video_id) mbid, youtube_video_id FROM matched
    WHERE track_id IS NULL AND youtube_video_id IS NOT NULL ORDER BY youtube_video_id, mbid
), adopted AS (
    SELECT c.mbid, l.track_id, l.is_manually_edited FROM candidate c JOIN legacy l USING (youtube_video_id)
)
SELECT m.mbid, m.title, m.artist, m.youtube_video_id, m.youtube_unplayable_reason, m.genre_name, c.uuid AS genre_id,
    COALESCE(m.track_id, a.track_id, gen_random_uuid()) AS track_id,
    m.track_id IS NULL AND a.track_id IS NULL AS is_new,
    a.track_id IS NOT NULL AS is_adopted,
    COALESCE(m.is_manually_edited, a.is_manually_edited, false) AS is_locked
FROM matched m
LEFT JOIN adopted a USING (mbid)
LEFT JOIN (grow_criteria c JOIN grow_genre g ON g.criteria_ptr_id = c.uuid)
    ON lower(c.name) = lower(m.genre_name) AND c.user_id IS NOT DISTINCT FROM %(user)s
"""

STEPS = [
    "ANALYZE song_import",
    """UPDATE grow_youtube_track y SET musicbrainz_recording_id = s.mbid
    FROM song_import s WHERE y.track_id = s.track_id AND s.is_adopted""",
    """CREATE TEMP TABLE track_genre_change AS
    SELECT s.track_id, t.genre_id AS old_genre_id, s.genre_id AS new_genre_id
    FROM song_import s JOIN the_music_tree_genre_kit_track t ON t.uuid = s.track_id
    WHERE NOT s.is_new AND NOT s.is_locked AND t.genre_id IS DISTINCT FROM s.genre_id""",
    """UPDATE the_music_tree_genre_kit_track t SET
        title = s.title, genre_id = CASE WHEN s.is_locked THEN t.genre_id ELSE s.genre_id END, updated_on = now()
    FROM song_import s WHERE t.uuid = s.track_id AND NOT s.is_new
        AND (t.title IS DISTINCT FROM s.title OR (NOT s.is_locked AND t.genre_id IS DISTINCT FROM s.genre_id))""",
    """UPDATE grow_youtube_track y SET
        youtube_video_id = s.youtube_video_id, youtube_unplayable_reason = s.youtube_unplayable_reason
    FROM song_import s WHERE y.track_id = s.track_id AND NOT s.is_new
        AND (y.youtube_video_id IS DISTINCT FROM s.youtube_video_id
            OR y.youtube_unplayable_reason IS DISTINCT FROM s.youtube_unplayable_reason)""",
    """INSERT INTO the_music_tree_genre_kit_track (uuid, created_on, play_count, title, genre_id, user_id)
    SELECT track_id, now(), 0, title, genre_id, %(user)s FROM song_import WHERE is_new""",
    """INSERT INTO grow_youtube_track
        (track_id, youtube_video_id, is_manually_edited, youtube_unplayable_reason, musicbrainz_recording_id)
    SELECT track_id, youtube_video_id, false, youtube_unplayable_reason, mbid FROM song_import WHERE is_new""",
    # ponytail: artists are only set on insert, like the old per-row import; re-sync them on matched tracks if
    # upstream artist-name corrections need to propagate.
    """INSERT INTO grow_artist (uuid, created_on, name, user_id)
    SELECT gen_random_uuid(), now(), n.artist, %(user)s FROM (SELECT DISTINCT artist FROM song_import WHERE is_new) n
    WHERE NOT EXISTS (SELECT 1 FROM grow_artist a WHERE a.name = n.artist AND a.user_id IS NOT DISTINCT FROM %(user)s)""",
    """INSERT INTO the_music_tree_genre_kit_track_artists (track_id, artist_id)
    SELECT s.track_id, a.uuid FROM song_import s JOIN (
        SELECT DISTINCT ON (name) uuid, name FROM grow_artist WHERE user_id IS NOT DISTINCT FROM %(user)s
        ORDER BY name, created_on
    ) a ON a.name = s.artist
    WHERE s.is_new""",
    """CREATE TEMP TABLE stale AS
    SELECT y.track_id FROM grow_youtube_track y JOIN the_music_tree_genre_kit_track t ON t.uuid = y.track_id
    WHERE t.user_id IS NOT DISTINCT FROM %(user)s AND NOT y.is_manually_edited
        AND NOT EXISTS (SELECT 1 FROM song_import s WHERE s.track_id = y.track_id)""",
    """CREATE TEMP TABLE stale_artist AS SELECT DISTINCT artist_id FROM the_music_tree_genre_kit_track_artists
    WHERE track_id IN (SELECT track_id FROM stale)""",
    """CREATE TEMP TABLE touched_playlist AS SELECT DISTINCT playlist_id FROM the_music_tree_genre_kit_track_playlist_rel
    WHERE track_id IN (SELECT track_id FROM stale)""",
    "DELETE FROM the_music_tree_genre_kit_track_playlist_rel WHERE track_id IN (SELECT track_id FROM stale)",
    "DELETE FROM grow_genre_essential_tracks WHERE youtubetrack_id IN (SELECT track_id FROM stale)",
    "DELETE FROM the_music_tree_genre_kit_track_artists WHERE track_id IN (SELECT track_id FROM stale)",
    "DELETE FROM grow_youtube_track WHERE track_id IN (SELECT track_id FROM stale)",
    "DELETE FROM the_music_tree_genre_kit_track WHERE uuid IN (SELECT track_id FROM stale)",
    """DELETE FROM grow_artist a WHERE a.uuid IN (SELECT artist_id FROM stale_artist)
        AND NOT EXISTS (SELECT 1 FROM the_music_tree_genre_kit_track_artists ta WHERE ta.artist_id = a.uuid)
        AND NOT EXISTS (SELECT 1 FROM grow_album_album_artists aa WHERE aa.artist_id = a.uuid)""",
    # Each genre's playlists: its own and every primary ascendant's. Genreless songs get none.
    """CREATE TEMP TABLE genre_playlist AS
    WITH RECURSIVE primary_parent AS (
        SELECT uuid AS child, parent_id AS parent FROM grow_criteria WHERE parent_id IS NOT NULL
        UNION SELECT from_criteria_id, to_criteria_id FROM grow_criteria_additional_primary_parents
    ), ascendant (genre_id, ascendant_id) AS (
        SELECT DISTINCT genre_id, genre_id FROM song_import WHERE genre_id IS NOT NULL
        UNION SELECT a.genre_id, p.parent FROM ascendant a JOIN primary_parent p ON p.child = a.ascendant_id
    )
    SELECT a.genre_id, cp.playlist_id FROM ascendant a JOIN grow_criteria_playlist cp ON cp.criteria_id = a.ascendant_id""",
    """CREATE TEMP TABLE desired_rel AS
    SELECT s.track_id, gp.playlist_id FROM song_import s JOIN genre_playlist gp USING (genre_id) WHERE s.is_new
    UNION ALL
    SELECT c.track_id, gp.playlist_id FROM track_genre_change c JOIN genre_playlist gp ON gp.genre_id = c.new_genre_id""",
    """WITH removed AS (
        DELETE FROM the_music_tree_genre_kit_track_playlist_rel r USING track_genre_change c
        WHERE r.track_id = c.track_id AND r.playlist_id IN (SELECT playlist_id FROM grow_criteria_playlist)
            AND NOT EXISTS (SELECT 1 FROM desired_rel d WHERE d.track_id = r.track_id AND d.playlist_id = r.playlist_id)
        RETURNING r.playlist_id
    )
    INSERT INTO touched_playlist SELECT DISTINCT playlist_id FROM removed""",
    """CREATE TEMP TABLE new_rel (id bigint, playlist_id uuid)""",
    """WITH inserted AS (
        INSERT INTO the_music_tree_genre_kit_track_playlist_rel (created_on, playlist_id, track_id, user_id)
        SELECT now(), d.playlist_id, d.track_id, %(user)s FROM desired_rel d
        WHERE NOT EXISTS (
            SELECT 1 FROM the_music_tree_genre_kit_track_playlist_rel r
            WHERE r.track_id = d.track_id AND r.playlist_id = d.playlist_id
        )
        RETURNING id, playlist_id
    )
    INSERT INTO new_rel SELECT id, playlist_id FROM inserted""",
    # LIFO like a single-row insert: new rels take positions 1..n (last inserted first), kept rels follow in order.
    """UPDATE the_music_tree_genre_kit_track_playlist_rel r SET position = o.position FROM (
        SELECT r.id, row_number() OVER (PARTITION BY r.playlist_id ORDER BY n.id IS NULL, n.id DESC, r.position) AS position
        FROM the_music_tree_genre_kit_track_playlist_rel r LEFT JOIN new_rel n ON n.id = r.id
        WHERE r.playlist_id IN (SELECT playlist_id FROM touched_playlist UNION SELECT playlist_id FROM new_rel)
            AND (r.position IS NOT NULL OR n.id IS NOT NULL)
    ) o WHERE r.id = o.id AND r.position IS DISTINCT FROM o.position""",
    """INSERT INTO grow_history_entry
        (uuid, created_on, object_pk, action, old_value, new_value, content_type_id, user_id, actor_id)
    SELECT gen_random_uuid(), now(), c.track_id, %(genre_changed)s, o.name, n.name, %(content_type)s, %(user)s, NULL
    FROM track_genre_change c
    LEFT JOIN grow_criteria o ON o.uuid = c.old_genre_id
    LEFT JOIN grow_criteria n ON n.uuid = c.new_genre_id""",
]


def merge_song_import_run(run_id: int, user_id: int | None, record: bool) -> dict[str, int]:
    """
    Merges a committed run's staged songs into the owner's `YoutubeTrack`s in one transaction: upsert by MBID
    (legacy MBID-less tracks adopted by video id), only changed rows written, locked (`is_manually_edited`) tracks
    keep their genre and are never deleted, every other track missing from the run is deleted, and genre-playlist
    rels follow genre changes. A genre name with no criteria match is stored as a null genre and counted as skipped.
    """
    params = {
        "run": run_id,
        "user": user_id,
        "genre_changed": HistoryAction.GENRE_CHANGED.value,
        "content_type": ContentType.objects.get_for_model(YoutubeTrack).pk,
    }
    try:
        return _merge(run_id, params, record)
    finally:
        # A failed merge rolls back, so its staged rows are dropped here instead of lingering until the next run.
        SongImportStaging.objects.filter(run_id=run_id).delete()
        SongImportRun.objects.filter(pk=run_id).delete()


def _merge(run_id: int, params: dict, record: bool) -> dict[str, int]:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {TEMP_TABLES}")
        cursor.execute(SONG_IMPORT, params)
        cursor.execute("SELECT EXISTS (SELECT 1 FROM song_import)")
        if not cursor.fetchone()[0]:
            # Every unlocked track missing from the run is deleted, so an empty run would wipe the library.
            raise ValueError(f"import run {run_id} has no staged songs")
        for step in STEPS:
            cursor.execute(step, params)
        cursor.execute(
            "SELECT count(*), count(*) FILTER (WHERE genre_name IS NOT NULL AND genre_id IS NULL) FROM song_import"
        )
        imported, skipped = cursor.fetchone()
        cursor.execute(f"DROP TABLE {TEMP_TABLES}")
        if record:
            ImportRun.objects.create(kind=ImportRun.Kind.SONGS, count=imported, skipped_count=skipped)
    return {"imported": imported, "skipped": skipped}
