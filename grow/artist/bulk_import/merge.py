from django.db import connection, transaction

from grow.artist.bulk_import.ArtistImportStaging import ArtistImportStaging
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.model.import_run.ImportRun import ImportRun

TEMP_TABLES = "artist_import, run_artist, release_group_import, stale_artist"

YEAR = "(({0})::int)"

STEPS = [
    # One row per MBID: a re-uploaded part's latest copy wins.
    """CREATE TEMP TABLE artist_import AS
    SELECT DISTINCT ON (musicbrainz_artist_id) musicbrainz_artist_id AS mbid, data
    FROM grow_artist_import_staging WHERE run_id = %(run)s ORDER BY musicbrainz_artist_id, part DESC""",
    "ANALYZE artist_import",
    f"""INSERT INTO grow_artist
        (uuid, created_on, name, user_id, musicbrainz_artist_id, type, country, begin_year, end_year, ended)
    SELECT gen_random_uuid(), now(), data->>'name', %(user)s, mbid, data->>'type', data->>'country',
        {YEAR.format("data->>'begin_year'")}, {YEAR.format("data->>'end_year'")}, (data->>'ended')::boolean
    FROM artist_import ORDER BY mbid
    ON CONFLICT (musicbrainz_artist_id) DO UPDATE SET
        name = EXCLUDED.name, type = EXCLUDED.type, country = EXCLUDED.country, begin_year = EXCLUDED.begin_year,
        end_year = EXCLUDED.end_year, ended = EXCLUDED.ended, updated_on = now()
    WHERE (grow_artist.name, grow_artist.type, grow_artist.country, grow_artist.begin_year, grow_artist.end_year,
        grow_artist.ended) IS DISTINCT FROM
        (EXCLUDED.name, EXCLUDED.type, EXCLUDED.country, EXCLUDED.begin_year, EXCLUDED.end_year, EXCLUDED.ended)""",
    """CREATE TEMP TABLE run_artist AS
    SELECT a.uuid, i.data FROM artist_import i JOIN grow_artist a ON a.musicbrainz_artist_id = i.mbid""",
    # Memberships, links and release-group credits of the run's artists are replaced wholesale.
    "DELETE FROM grow_artist_membership WHERE group_id IN (SELECT uuid FROM run_artist)",
    f"""INSERT INTO grow_artist_membership (group_id, member_id, begin_year, end_year, ended, roles)
    SELECT r.uuid, m.uuid, {YEAR.format("e->>'begin_year'")}, {YEAR.format("e->>'end_year'")},
        (e->>'ended')::boolean, e->'roles'
    FROM run_artist r CROSS JOIN jsonb_array_elements(r.data->'members') e
    JOIN grow_artist m ON m.musicbrainz_artist_id = (e->>'musicbrainz_artist_id')::uuid""",
    "DELETE FROM grow_artist_link WHERE artist_id IN (SELECT uuid FROM run_artist)",
    """INSERT INTO grow_artist_link (artist_id, kind, url)
    SELECT DISTINCT r.uuid, e->>'kind', e->>'url' FROM run_artist r CROSS JOIN jsonb_array_elements(r.data->'links') e""",
    """CREATE TEMP TABLE release_group_import AS
    SELECT DISTINCT ON (mbid) mbid, e->>'title' AS title, e->>'primary_type' AS primary_type,
        e->'secondary_types' AS secondary_types, (e->>'first_release_year') AS year
    FROM (
        SELECT (e->>'musicbrainz_release_group_id')::uuid AS mbid, e
        FROM run_artist r CROSS JOIN jsonb_array_elements(r.data->'release_groups') e
    ) g ORDER BY mbid""",
    """INSERT INTO grow_album
        (uuid, created_on, name, user_id, year, musicbrainz_release_group_id, primary_type, secondary_types)
    SELECT gen_random_uuid(), now(), title, %(user)s, year, mbid, primary_type, secondary_types
    FROM release_group_import ORDER BY mbid
    ON CONFLICT (musicbrainz_release_group_id) DO UPDATE SET
        name = EXCLUDED.name, year = EXCLUDED.year, primary_type = EXCLUDED.primary_type,
        secondary_types = EXCLUDED.secondary_types, updated_on = now()
    WHERE (grow_album.name, grow_album.year, grow_album.primary_type, grow_album.secondary_types) IS DISTINCT FROM
        (EXCLUDED.name, EXCLUDED.year, EXCLUDED.primary_type, EXCLUDED.secondary_types)""",
    """DELETE FROM grow_album_album_artists aa USING grow_album al
    WHERE al.uuid = aa.album_id AND al.musicbrainz_release_group_id IS NOT NULL
        AND aa.artist_id IN (SELECT uuid FROM run_artist)""",
    """INSERT INTO grow_album_album_artists (album_id, artist_id)
    SELECT DISTINCT al.uuid, r.uuid FROM run_artist r CROSS JOIN jsonb_array_elements(r.data->'release_groups') e
    JOIN grow_album al ON al.musicbrainz_release_group_id = (e->>'musicbrainz_release_group_id')::uuid
    WHERE NOT EXISTS (SELECT 1 FROM grow_album_album_artists x WHERE x.album_id = al.uuid AND x.artist_id = r.uuid)""",
    # The artists import owns the reference artists' lifecycle: one missing from the run goes once no track or
    # hand-made (non release-group) album credits it.
    """CREATE TEMP TABLE stale_artist AS
    SELECT a.uuid FROM grow_artist a
    WHERE a.user_id IS NOT DISTINCT FROM %(user)s AND a.uuid NOT IN (SELECT uuid FROM run_artist)
        AND NOT EXISTS (SELECT 1 FROM the_music_tree_genre_kit_track_artists ta WHERE ta.artist_id = a.uuid)
        AND NOT EXISTS (
            SELECT 1 FROM grow_album_album_artists aa JOIN grow_album al ON al.uuid = aa.album_id
            WHERE aa.artist_id = a.uuid AND al.musicbrainz_release_group_id IS NULL
        )""",
    """DELETE FROM grow_artist_membership
    WHERE group_id IN (SELECT uuid FROM stale_artist) OR member_id IN (SELECT uuid FROM stale_artist)""",
    "DELETE FROM grow_artist_link WHERE artist_id IN (SELECT uuid FROM stale_artist)",
    "DELETE FROM grow_album_album_artists WHERE artist_id IN (SELECT uuid FROM stale_artist)",
    "DELETE FROM grow_artist WHERE uuid IN (SELECT uuid FROM stale_artist)",
    """DELETE FROM grow_album al WHERE al.musicbrainz_release_group_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM grow_album_album_artists aa WHERE aa.album_id = al.uuid)
        AND NOT EXISTS (SELECT 1 FROM the_music_tree_genre_kit_track t WHERE t.album_id = al.uuid)""",
]


def merge_artist_import_run(run_id: int, user_id: int | None, record: bool) -> dict[str, int]:
    """
    Merges a committed run's staged artists in one transaction: artists upserted on MBID with their details, their
    memberships, links and release-group albums (with album artists) replaced, and every artist missing from the
    run deleted once nothing credits it. Run after the songs import so song artists already carry their MBID.
    """
    try:
        return _merge(run_id, {"run": run_id, "user": user_id}, record)
    finally:
        # A failed merge rolls back, so its staged rows are dropped here instead of lingering until the next run.
        ArtistImportStaging.objects.filter(run_id=run_id).delete()
        BulkImportRun.objects.filter(pk=run_id).delete()


def _merge(run_id: int, params: dict, record: bool) -> dict[str, int]:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {TEMP_TABLES}")
        cursor.execute("SELECT EXISTS (SELECT 1 FROM grow_artist_import_staging WHERE run_id = %(run)s)", params)
        if not cursor.fetchone()[0]:
            # Artists missing from the run are deleted, so an empty run would wipe every uncredited artist.
            raise ValueError(f"import run {run_id} has no staged artists")
        for step in STEPS:
            cursor.execute(step, params)
        cursor.execute("SELECT count(*) FROM run_artist")
        (imported,) = cursor.fetchone()
        cursor.execute(f"DROP TABLE {TEMP_TABLES}")
        if record:
            ImportRun.objects.create(kind=ImportRun.Kind.ARTISTS, count=imported, skipped_count=0)
    return {"imported": imported, "skipped": 0}
