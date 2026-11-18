"""
The SQL deriving `grow_song_search` rows from the source tables. The bulk merges, the ORM refresh, the rebuild command
and the drift check all go through it, so the projection has a single definition.
"""

from grow.song_search.rank import HAS_GENRE_SQL, PLAYABLE_SQL, RANK_SCORE_SQL

TABLE = "grow_song_search"
COLUMNS = "track_id, document, title_key, has_genre, playable, rank_score"
TITLE_KEY_LEN_MAX = 200
QUERY_TOKENS_MAX = 8


def words(expression: str) -> str:
    """
    Folds accents and case, then keeps only letters and digits, space-separated. The text-search parser would read
    `ac/dc`, `m.i.a.` or `2.0` as single file/host/number tokens that the query's `\\w` tokens never match, so it only
    ever sees plain words. Search queries must be folded through it too.
    """
    return f"btrim(regexp_replace(grow_search_norm({expression}), '[^[:alnum:]]+', ' ', 'g'))"


# Artists in credit order, so a rebuilt document is identical to an incrementally maintained one.
PROJECTION = f"""SELECT t.uuid AS track_id,
    setweight(to_tsvector('simple', {words("t.title")}), 'A')
        || setweight(to_tsvector('simple', {words("coalesce(a.names, '')")}), 'B') AS document,
    left({words("t.title")}, {TITLE_KEY_LEN_MAX}) AS title_key,
    {HAS_GENRE_SQL} AS has_genre,
    {PLAYABLE_SQL} AS playable,
    {RANK_SCORE_SQL} AS rank_score
FROM grow_song s
JOIN the_music_tree_genre_kit_track t ON t.uuid = s.track_id
LEFT JOIN LATERAL (
    SELECT string_agg(ar.name, ' ' ORDER BY ta.id) AS names
    FROM the_music_tree_genre_kit_track_artists ta JOIN grow_artist ar ON ar.uuid = ta.artist_id
    WHERE ta.track_id = s.track_id
) a ON true"""


def lock_if_live(cursor) -> bool:
    """
    Whether the projection is built (`ready`), taking a ROW EXCLUSIVE lock on it first. The lock conflicts with the
    rebuild's EXCLUSIVE one, so a merge and a rebuild serialize: a merge locking first makes the rebuild wait and then
    see its songs; a rebuild locking first makes the merge wait for the swap and read `ready = true`. Postgres-only.
    """
    cursor.execute(f"LOCK TABLE {TABLE} IN ROW EXCLUSIVE MODE")
    cursor.execute("SELECT coalesce((SELECT ready FROM grow_song_search_state WHERE id = 1), false)")
    return bool(cursor.fetchone()[0])


def upsert(track_ids_sql: str, table: str = TABLE) -> str:
    """Upserts the projection of the songs whose id `track_ids_sql` (a subquery) selects; unchanged rows are not
    rewritten, so a nightly run leaves no dead tuples for the songs it didn't touch."""
    return f"""INSERT INTO {table} ({COLUMNS})
{PROJECTION}
WHERE s.track_id IN ({track_ids_sql})
ORDER BY s.track_id
ON CONFLICT (track_id) DO UPDATE SET
    document = EXCLUDED.document, title_key = EXCLUDED.title_key, has_genre = EXCLUDED.has_genre,
    playable = EXCLUDED.playable, rank_score = EXCLUDED.rank_score
WHERE ({table}.document, {table}.title_key, {table}.has_genre, {table}.playable, {table}.rank_score)
    IS DISTINCT FROM (EXCLUDED.document, EXCLUDED.title_key, EXCLUDED.has_genre, EXCLUDED.playable,
        EXCLUDED.rank_score)"""


def delete(track_ids_sql: str) -> str:
    return f"DELETE FROM {TABLE} WHERE track_id IN ({track_ids_sql})"


DRIFT = f"""WITH expected AS ({PROJECTION})
SELECT
    (SELECT count(*) FROM expected e WHERE NOT EXISTS (SELECT 1 FROM {TABLE} p WHERE p.track_id = e.track_id)),
    (SELECT count(*) FROM {TABLE} p WHERE NOT EXISTS (SELECT 1 FROM grow_song s WHERE s.track_id = p.track_id)),
    (SELECT count(*) FROM expected e JOIN {TABLE} p USING (track_id)
        WHERE (p.document, p.title_key, p.has_genre, p.playable, p.rank_score)
            IS DISTINCT FROM (e.document, e.title_key, e.has_genre, e.playable, e.rank_score))"""
