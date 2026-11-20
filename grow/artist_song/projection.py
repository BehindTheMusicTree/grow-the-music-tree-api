"""
The SQL deriving `grow_artist_song` rows from the source tables: one row per (artist, song) credit, carrying the two
sort keys of the artist's song list, so a page is an index range scan whatever the artist's size. The bulk merges, the
ORM refresh, the rebuild command and the drift check all go through it, so the projection has a single definition.
"""

TABLE = "grow_artist_song"
STATE_TABLE = "grow_artist_song_state"
COLUMNS = "artist_id, song_id, title, album_year"
# SQL routines the projection calls: their definitions are part of its fingerprint.
FUNCTIONS: tuple[str, ...] = ()

# Mirrors `ORDERINGS["albumYear"]` in grow/filtering/set/song/SongFilterSet.py: the song's first-release year, else its
# album's (a free-text column, so only four-digit years cast).
ALBUM_YEAR_SQL = "coalesce(s.first_release_year, CASE WHEN al.year ~ '^[0-9]{4}$' THEN al.year::smallint END)"

PROJECTION = f"""SELECT ta.artist_id, s.track_id AS song_id, t.title, {ALBUM_YEAR_SQL} AS album_year
FROM grow_song s
JOIN the_music_tree_genre_kit_track t ON t.uuid = s.track_id
JOIN the_music_tree_genre_kit_track_artists ta ON ta.track_id = s.track_id
LEFT JOIN grow_album al ON al.uuid = t.album_id"""


def lock_if_live(cursor) -> bool:
    """
    Whether the projection is built (`ready`), taking a ROW EXCLUSIVE lock on it first. The lock conflicts with the
    rebuild's EXCLUSIVE one, so a merge and a rebuild serialize (see `grow.song_search.projection.lock_if_live`).
    Postgres-only.
    """
    cursor.execute(f"LOCK TABLE {TABLE} IN ROW EXCLUSIVE MODE")
    cursor.execute(f"SELECT coalesce((SELECT ready FROM {STATE_TABLE} WHERE id = 1), false)")
    return bool(cursor.fetchone()[0])


def upsert(song_ids_sql: str) -> str:
    """Upserts the rows of the songs `song_ids_sql` (a subquery) selects; unchanged rows are not rewritten."""
    return f"""INSERT INTO {TABLE} ({COLUMNS})
{PROJECTION}
WHERE s.track_id IN ({song_ids_sql})
ORDER BY ta.artist_id, s.track_id
ON CONFLICT (artist_id, song_id) DO UPDATE SET title = EXCLUDED.title, album_year = EXCLUDED.album_year
WHERE ({TABLE}.title, {TABLE}.album_year) IS DISTINCT FROM (EXCLUDED.title, EXCLUDED.album_year)"""


def delete_removed_links(song_ids_sql: str) -> str:
    """Deletes the rows of the given songs whose credit no longer exists, and every row of a deleted song."""
    return f"""DELETE FROM {TABLE} p WHERE p.song_id IN ({song_ids_sql})
    AND NOT EXISTS (SELECT 1 FROM the_music_tree_genre_kit_track_artists ta
        JOIN grow_song s ON s.track_id = ta.track_id
        WHERE ta.track_id = p.song_id AND ta.artist_id = p.artist_id)"""


def delete_songs(song_ids_sql: str) -> str:
    return f"DELETE FROM {TABLE} WHERE song_id IN ({song_ids_sql})"


def songs_of_albums(album_ids_sql: str) -> str:
    return f"SELECT t.uuid FROM the_music_tree_genre_kit_track t WHERE t.album_id IN ({album_ids_sql})"


DRIFT = f"""WITH expected AS ({PROJECTION})
SELECT
    (SELECT count(*) FROM expected e
        WHERE NOT EXISTS (SELECT 1 FROM {TABLE} p WHERE p.artist_id = e.artist_id AND p.song_id = e.song_id)),
    (SELECT count(*) FROM {TABLE} p WHERE NOT EXISTS (
        SELECT 1 FROM the_music_tree_genre_kit_track_artists ta JOIN grow_song s ON s.track_id = ta.track_id
        WHERE ta.track_id = p.song_id AND ta.artist_id = p.artist_id)),
    (SELECT count(*) FROM expected e JOIN {TABLE} p USING (artist_id, song_id)
        WHERE (p.title, p.album_year) IS DISTINCT FROM (e.title, e.album_year))"""
