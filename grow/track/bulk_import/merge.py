from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from the_music_tree_genre_kit.criteria.type.CriteriaTypePks import CriteriaTypePks

from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.model.history.HistoryAction import HistoryAction
from grow.model.import_run.ImportRun import ImportRun
from grow.model.recording.Recording import Recording
from grow.track.bulk_import.SongImportStaging import SongImportStaging

TEMP_TABLES = "song_import, genre_playlist, genreless_playlist, track_change, desired_rel, new_rel, touched_playlist, stale, desired_artist"

# One song per MBID (a re-uploaded part's latest copy wins), matched to the owner's track by MBID, else a legacy
# MBID-less track adopted by video id (one song per video), else a new track id.
SONG_IMPORT = """
CREATE TEMP TABLE song_import AS
WITH staged AS (
    SELECT DISTINCT ON (musicbrainz_recording_id)
        musicbrainz_recording_id AS mbid, title, artist, artist_musicbrainz_id AS artist_mbid, youtube_video_id,
        youtube_unplayable_reason, genre_name
    FROM grow_song_import_staging WHERE run_id = %(run)s
    ORDER BY musicbrainz_recording_id, part DESC
), owned AS (
    SELECT y.track_id, y.musicbrainz_recording_id, y.youtube_video_id, y.is_manually_edited
    FROM grow_recording y JOIN the_music_tree_genre_kit_track t ON t.uuid = y.track_id
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
SELECT m.mbid, m.title, m.artist, m.artist_mbid, m.youtube_video_id, m.youtube_unplayable_reason, m.genre_name, c.uuid AS genre_id,
    COALESCE(m.track_id, a.track_id, gen_random_uuid()) AS track_id,
    m.track_id IS NULL AND a.track_id IS NULL AS is_new,
    a.track_id IS NOT NULL AS is_adopted,
    COALESCE(m.is_manually_edited, a.is_manually_edited, false) AS is_locked
FROM matched m
LEFT JOIN adopted a USING (mbid)
LEFT JOIN (grow_criteria c JOIN grow_genre g ON g.criteria_ptr_id = c.uuid)
    ON lower(c.name) = lower(m.genre_name) AND c.user_id IS NOT DISTINCT FROM %(user)s
"""

# Same predicate as TrackManager._is_playable: only playable recordings belong to playlists.
PLAYABLE = "{0}.youtube_video_id IS NOT NULL AND {0}.youtube_unplayable_reason IS NULL"

STEPS = [
    "ANALYZE song_import",
    """UPDATE grow_recording y SET musicbrainz_recording_id = s.mbid
    FROM song_import s WHERE y.track_id = s.track_id AND s.is_adopted""",
    # Playlist membership changes when the genre (locked tracks keep theirs) or the playability changes. Captured
    # before the updates below, from the stored values and the incoming ones the updates write.
    f"""CREATE TEMP TABLE track_change AS
    SELECT * FROM (
        SELECT s.track_id, t.genre_id AS old_genre_id,
            CASE WHEN s.is_locked THEN t.genre_id ELSE s.genre_id END AS new_genre_id,
            {PLAYABLE.format("y")} AS was_playable, {PLAYABLE.format("s")} AS is_playable
        FROM song_import s
        JOIN the_music_tree_genre_kit_track t ON t.uuid = s.track_id
        JOIN grow_recording y ON y.track_id = s.track_id
        WHERE NOT s.is_new
    ) c WHERE old_genre_id IS DISTINCT FROM new_genre_id OR was_playable IS DISTINCT FROM is_playable""",
    """UPDATE the_music_tree_genre_kit_track t SET
        title = s.title, genre_id = CASE WHEN s.is_locked THEN t.genre_id ELSE s.genre_id END, updated_on = now()
    FROM song_import s WHERE t.uuid = s.track_id AND NOT s.is_new
        AND (t.title IS DISTINCT FROM s.title OR (NOT s.is_locked AND t.genre_id IS DISTINCT FROM s.genre_id))""",
    """UPDATE grow_recording y SET
        youtube_video_id = s.youtube_video_id, youtube_unplayable_reason = s.youtube_unplayable_reason
    FROM song_import s WHERE y.track_id = s.track_id AND NOT s.is_new
        AND (y.youtube_video_id IS DISTINCT FROM s.youtube_video_id
            OR y.youtube_unplayable_reason IS DISTINCT FROM s.youtube_unplayable_reason)""",
    # Key order fills the pkey/track_id btrees sequentially instead of evicting a random index page per row.
    """INSERT INTO the_music_tree_genre_kit_track (uuid, created_on, play_count, title, genre_id, user_id)
    SELECT track_id, now(), 0, title, genre_id, %(user)s FROM song_import WHERE is_new
    ORDER BY track_id""",
    """INSERT INTO grow_recording
        (track_id, youtube_video_id, is_manually_edited, youtube_unplayable_reason, musicbrainz_recording_id)
    SELECT track_id, youtube_video_id, false, youtube_unplayable_reason, mbid FROM song_import WHERE is_new
    ORDER BY track_id""",
    # A legacy MBID-less artist with the song's artist name takes the MBID instead of a duplicate being created
    # (one legacy artist per name, one per MBID).
    """UPDATE grow_artist a SET musicbrainz_artist_id = c.mbid FROM (
        SELECT DISTINCT ON (s.mbid) l.uuid, s.mbid
        FROM (
            SELECT DISTINCT ON (artist) artist, artist_mbid AS mbid FROM song_import
            WHERE artist_mbid IS NOT NULL ORDER BY artist, artist_mbid
        ) s
        JOIN (
            SELECT DISTINCT ON (name) uuid, name FROM grow_artist
            WHERE musicbrainz_artist_id IS NULL AND user_id IS NOT DISTINCT FROM %(user)s ORDER BY name, created_on
        ) l ON l.name = s.artist
        WHERE NOT EXISTS (SELECT 1 FROM grow_artist x WHERE x.musicbrainz_artist_id = s.mbid)
        ORDER BY s.mbid, l.uuid
    ) c WHERE a.uuid = c.uuid""",
    # Details come with the artists import; a song only brings its artist's name and MBID.
    """INSERT INTO grow_artist (uuid, created_on, name, user_id, musicbrainz_artist_id, ended)
    SELECT gen_random_uuid(), now(), n.artist, %(user)s, n.mbid, false FROM (
        SELECT DISTINCT ON (artist_mbid) artist_mbid AS mbid, artist FROM song_import
        WHERE artist_mbid IS NOT NULL ORDER BY artist_mbid, artist
    ) n
    ON CONFLICT (musicbrainz_artist_id) DO NOTHING""",
    """INSERT INTO grow_artist (uuid, created_on, name, user_id, ended)
    SELECT gen_random_uuid(), now(), n.artist, %(user)s, false
    FROM (SELECT DISTINCT artist FROM song_import WHERE artist_mbid IS NULL) n
    WHERE NOT EXISTS (SELECT 1 FROM grow_artist a WHERE a.name = n.artist AND a.user_id IS NOT DISTINCT FROM %(user)s)""",
    # Every run re-syncs track artists, so upstream artist corrections reach existing tracks.
    """CREATE TEMP TABLE desired_artist AS
    SELECT s.track_id, COALESCE(m.uuid, n.uuid) AS artist_id FROM song_import s
    LEFT JOIN grow_artist m ON m.musicbrainz_artist_id = s.artist_mbid
    LEFT JOIN (
        SELECT DISTINCT ON (name) uuid, name FROM grow_artist WHERE user_id IS NOT DISTINCT FROM %(user)s
        ORDER BY name, created_on
    ) n ON s.artist_mbid IS NULL AND n.name = s.artist""",
    """DELETE FROM the_music_tree_genre_kit_track_artists ta USING song_import s
    WHERE ta.track_id = s.track_id
        AND NOT EXISTS (SELECT 1 FROM desired_artist d WHERE d.track_id = ta.track_id AND d.artist_id = ta.artist_id)""",
    """INSERT INTO the_music_tree_genre_kit_track_artists (track_id, artist_id)
    SELECT d.track_id, d.artist_id FROM desired_artist d
    WHERE NOT EXISTS (
        SELECT 1 FROM the_music_tree_genre_kit_track_artists ta WHERE ta.track_id = d.track_id AND ta.artist_id = d.artist_id
    )
    ORDER BY d.track_id""",
    """CREATE TEMP TABLE stale AS
    SELECT y.track_id FROM grow_recording y JOIN the_music_tree_genre_kit_track t ON t.uuid = y.track_id
    WHERE t.user_id IS NOT DISTINCT FROM %(user)s AND NOT y.is_manually_edited
        AND NOT EXISTS (SELECT 1 FROM song_import s WHERE s.track_id = y.track_id)""",
    """CREATE TEMP TABLE touched_playlist AS SELECT DISTINCT playlist_id FROM the_music_tree_genre_kit_track_playlist_rel
    WHERE track_id IN (SELECT track_id FROM stale)""",
    "DELETE FROM the_music_tree_genre_kit_track_playlist_rel WHERE track_id IN (SELECT track_id FROM stale)",
    "DELETE FROM grow_genre_essential_tracks WHERE recording_id IN (SELECT track_id FROM stale)",
    "DELETE FROM the_music_tree_genre_kit_track_artists WHERE track_id IN (SELECT track_id FROM stale)",
    "DELETE FROM grow_recording WHERE track_id IN (SELECT track_id FROM stale)",
    "DELETE FROM the_music_tree_genre_kit_track WHERE uuid IN (SELECT track_id FROM stale)",
    # Each genre's playlists: its own and every primary ascendant's; genreless songs get the genreless playlist.
    """CREATE TEMP TABLE genre_playlist AS
    WITH RECURSIVE primary_parent AS (
        SELECT uuid AS child, parent_id AS parent FROM grow_criteria WHERE parent_id IS NOT NULL
        UNION SELECT from_criteria_id, to_criteria_id FROM grow_criteria_additional_primary_parents
    ), ascendant (genre_id, ascendant_id) AS (
        SELECT genre_id, genre_id FROM (SELECT genre_id FROM song_import UNION SELECT new_genre_id FROM track_change) g
        WHERE genre_id IS NOT NULL
        UNION SELECT a.genre_id, p.parent FROM ascendant a JOIN primary_parent p ON p.child = a.ascendant_id
    )
    SELECT a.genre_id, cp.playlist_id FROM ascendant a JOIN grow_criteria_playlist cp ON cp.criteria_id = a.ascendant_id""",
    """CREATE TEMP TABLE genreless_playlist AS
    SELECT cp.playlist_id FROM grow_criteria_playlist cp JOIN the_music_tree_genre_kit_playlist p ON p.uuid = cp.playlist_id
    WHERE cp.criteria_id IS NULL AND cp.type_id = %(genre_type)s AND p.user_id IS NOT DISTINCT FROM %(user)s""",
    f"""CREATE TEMP TABLE desired_rel AS
    SELECT s.track_id, gp.playlist_id FROM song_import s JOIN genre_playlist gp USING (genre_id)
    WHERE s.is_new AND {PLAYABLE.format("s")}
    UNION ALL
    SELECT s.track_id, g.playlist_id FROM song_import s CROSS JOIN genreless_playlist g
    WHERE s.is_new AND s.genre_id IS NULL AND {PLAYABLE.format("s")}
    UNION ALL
    SELECT c.track_id, gp.playlist_id FROM track_change c JOIN genre_playlist gp ON gp.genre_id = c.new_genre_id
    WHERE c.is_playable
    UNION ALL
    SELECT c.track_id, g.playlist_id FROM track_change c CROSS JOIN genreless_playlist g
    WHERE c.is_playable AND c.new_genre_id IS NULL""",
    """WITH removed AS (
        DELETE FROM the_music_tree_genre_kit_track_playlist_rel r USING track_change c
        WHERE r.track_id = c.track_id
            AND r.playlist_id IN (SELECT playlist_id FROM grow_criteria_playlist WHERE type_id = %(genre_type)s)
            AND NOT EXISTS (SELECT 1 FROM desired_rel d WHERE d.track_id = r.track_id AND d.playlist_id = r.playlist_id)
        RETURNING r.playlist_id
    )
    INSERT INTO touched_playlist SELECT DISTINCT playlist_id FROM removed""",
    """CREATE TEMP TABLE new_rel (id bigint, playlist_id uuid)""",
    # LIFO like a single-row insert: new rels take positions 1..n (last inserted first), kept rels follow in order.
    # Positions are set at insert time: updating a row inserted in the same transaction re-runs its FK checks.
    """WITH inserted AS (
        INSERT INTO the_music_tree_genre_kit_track_playlist_rel (created_on, playlist_id, track_id, user_id, position)
        SELECT now(), d.playlist_id, d.track_id, %(user)s,
            row_number() OVER (PARTITION BY d.playlist_id ORDER BY d.track_id DESC)
        FROM desired_rel d
        WHERE NOT EXISTS (
            SELECT 1 FROM the_music_tree_genre_kit_track_playlist_rel r
            WHERE r.track_id = d.track_id AND r.playlist_id = d.playlist_id
        )
        ORDER BY d.playlist_id, d.track_id
        RETURNING id, playlist_id
    )
    INSERT INTO new_rel SELECT id, playlist_id FROM inserted""",
    """UPDATE the_music_tree_genre_kit_track_playlist_rel r SET position = o.position FROM (
        SELECT r.id, coalesce(n.added, 0) + row_number() OVER (PARTITION BY r.playlist_id ORDER BY r.position) AS position
        FROM the_music_tree_genre_kit_track_playlist_rel r
        LEFT JOIN (SELECT playlist_id, count(*) AS added FROM new_rel GROUP BY playlist_id) n USING (playlist_id)
        WHERE r.playlist_id IN (SELECT playlist_id FROM touched_playlist UNION SELECT playlist_id FROM new_rel)
            AND r.position IS NOT NULL AND NOT EXISTS (SELECT 1 FROM new_rel x WHERE x.id = r.id)
    ) o WHERE r.id = o.id AND r.position IS DISTINCT FROM o.position""",
    """INSERT INTO grow_history_entry
        (uuid, created_on, object_pk, action, old_value, new_value, content_type_id, user_id, actor_id)
    SELECT gen_random_uuid(), now(), c.track_id, %(genre_changed)s, o.name, n.name, %(content_type)s, %(user)s, NULL
    FROM track_change c
    LEFT JOIN grow_criteria o ON o.uuid = c.old_genre_id
    LEFT JOIN grow_criteria n ON n.uuid = c.new_genre_id
    WHERE c.old_genre_id IS DISTINCT FROM c.new_genre_id""",
]


def merge_song_import_run(run_id: int, user_id: int | None, record: bool) -> dict[str, int]:
    """
    Merges a committed run's staged songs into the owner's `Recording`s in one transaction: upsert by MBID
    (legacy MBID-less tracks adopted by video id), only changed rows written, locked (`is_manually_edited`) tracks
    keep their genre and are never deleted, every other track missing from the run is deleted, and genre-playlist
    rels follow genre and playability changes, holding playable recordings only. Track artists are re-synced: matched
    on MBID (a legacy MBID-less artist of the same name adopted), else on name; orphaned artists are left to the
    artists import, which owns their lifecycle. A genre name with no criteria match
    is stored as a null genre and counted as skipped.
    """
    params = {
        "run": run_id,
        "user": user_id,
        "genre_changed": HistoryAction.GENRE_CHANGED.value,
        "genre_type": CriteriaTypePks.GENRE.value,
        "content_type": ContentType.objects.get_for_model(Recording).pk,
    }
    try:
        return _merge(run_id, params, record)
    finally:
        # A failed merge rolls back, so its staged rows are dropped here instead of lingering until the next run.
        SongImportStaging.objects.filter(run_id=run_id).delete()
        BulkImportRun.objects.filter(pk=run_id).delete()


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
