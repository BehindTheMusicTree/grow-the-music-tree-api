from django.db import connection, transaction

from grow.artist.bulk_import.ArtistImportStaging import ArtistImportStaging
from grow.artist.search_cache import invalidate_search_cache
from grow.bulk_import.BulkImportDeletion import BulkImportDeletion
from grow.bulk_import.BulkImportRun import BulkImportRun
from grow.bulk_import.merge_lock import hold_merge_lock
from grow.bulk_import.run_steps import run_steps
from grow.model.import_run.ImportRun import ImportRun

TEMP_TABLES = (
    "artist_import, run_artist, membership_import, link_import, alias_import, release_group_row, "
    "release_group_import, credit_import, run_album, desired_membership, desired_link, desired_alias, "
    "desired_album_artist, stale_artist"
)

YEAR = "(({0})::int)"

# Every JSON array is expanded once into a narrow typed table, then keyed and ANALYZEd: later steps join those, never
# the jsonb again. `artist_import` keeps the winning staging row's id to reach each array.
EXPANDED_STEPS = [
    # One row per MBID: a re-uploaded part's latest copy wins.
    (
        "artist_import",
        f"""CREATE TEMP TABLE artist_import AS
    SELECT DISTINCT ON (musicbrainz_artist_id) musicbrainz_artist_id AS mbid, id AS staging_id, data->>'name' AS name,
        data->>'type' AS type, data->>'country' AS country, {YEAR.format("data->>'begin_year'")} AS begin_year,
        {YEAR.format("data->>'end_year'")} AS end_year, (data->>'ended')::boolean AS ended,
        data->>'disambiguation' AS disambiguation
    FROM grow_artist_import_staging WHERE run_id = %(run)s ORDER BY musicbrainz_artist_id, part DESC""",
    ),
    ("artist_import_pkey", "ALTER TABLE artist_import ADD PRIMARY KEY (mbid)"),
    ("analyze_artist_import", "ANALYZE artist_import"),
    (
        "membership_import",
        f"""CREATE TEMP TABLE membership_import AS
    SELECT i.mbid AS group_mbid, (e->>'musicbrainz_artist_id')::uuid AS member_mbid,
        {YEAR.format("e->>'begin_year'")} AS begin_year, {YEAR.format("e->>'end_year'")} AS end_year,
        (e->>'ended')::boolean AS ended, e->'roles' AS roles
    FROM artist_import i JOIN grow_artist_import_staging s ON s.id = i.staging_id
    CROSS JOIN jsonb_array_elements(s.data->'members') e""",
    ),
    ("analyze_membership_import", "ANALYZE membership_import"),
    (
        "link_import",
        """CREATE TEMP TABLE link_import AS
    SELECT DISTINCT i.mbid AS artist_mbid, e->>'kind' AS kind, e->>'url' AS url
    FROM artist_import i JOIN grow_artist_import_staging s ON s.id = i.staging_id
    CROSS JOIN jsonb_array_elements(s.data->'links') e""",
    ),
    ("analyze_link_import", "ANALYZE link_import"),
    # Parts exported before aliases existed have no `aliases` key: they stage as an empty list.
    (
        "alias_import",
        """CREATE TEMP TABLE alias_import AS
    SELECT DISTINCT i.mbid AS artist_mbid, e AS name
    FROM artist_import i JOIN grow_artist_import_staging s ON s.id = i.staging_id
    CROSS JOIN jsonb_array_elements_text(COALESCE(s.data->'aliases', '[]'::jsonb)) e""",
    ),
    ("analyze_alias_import", "ANALYZE alias_import"),
    (
        "release_group_row",
        """CREATE TEMP TABLE release_group_row AS
    SELECT i.mbid AS artist_mbid, (e->>'musicbrainz_release_group_id')::uuid AS mbid, e->>'title' AS title,
        e->>'primary_type' AS primary_type, e->'secondary_types' AS secondary_types, e->>'first_release_year' AS year
    FROM artist_import i JOIN grow_artist_import_staging s ON s.id = i.staging_id
    CROSS JOIN jsonb_array_elements(s.data->'release_groups') e""",
    ),
    (
        "release_group_import",
        """CREATE TEMP TABLE release_group_import AS
    SELECT DISTINCT ON (mbid) mbid, title, primary_type, secondary_types, year FROM release_group_row ORDER BY mbid""",
    ),
    ("release_group_import_pkey", "ALTER TABLE release_group_import ADD PRIMARY KEY (mbid)"),
    ("analyze_release_group_import", "ANALYZE release_group_import"),
    (
        "credit_import",
        "CREATE TEMP TABLE credit_import AS SELECT DISTINCT mbid AS release_group_mbid, artist_mbid FROM release_group_row",
    ),
    ("drop_release_group_row", "DROP TABLE release_group_row"),
    ("analyze_credit_import", "ANALYZE credit_import"),
]

# MBIDs are resolved to uuids once, here; the diff steps join these maps.
RESOLVE_STEPS = [
    (
        "upsert_artists",
        """INSERT INTO grow_artist
        (uuid, created_on, name, user_id, musicbrainz_artist_id, type, country, begin_year, end_year, ended,
        disambiguation)
    SELECT gen_random_uuid(), now(), name, %(user)s, mbid, type, country, begin_year, end_year, ended, disambiguation
    FROM artist_import ORDER BY mbid
    ON CONFLICT (musicbrainz_artist_id) DO UPDATE SET
        name = EXCLUDED.name, type = EXCLUDED.type, country = EXCLUDED.country, begin_year = EXCLUDED.begin_year,
        end_year = EXCLUDED.end_year, ended = EXCLUDED.ended, disambiguation = EXCLUDED.disambiguation,
        updated_on = now()
    WHERE (grow_artist.name, grow_artist.type, grow_artist.country, grow_artist.begin_year, grow_artist.end_year,
        grow_artist.ended, grow_artist.disambiguation) IS DISTINCT FROM
        (EXCLUDED.name, EXCLUDED.type, EXCLUDED.country, EXCLUDED.begin_year, EXCLUDED.end_year, EXCLUDED.ended,
        EXCLUDED.disambiguation)""",
    ),
    (
        "run_artist",
        """CREATE TEMP TABLE run_artist AS
    SELECT i.mbid, a.uuid FROM artist_import i JOIN grow_artist a ON a.musicbrainz_artist_id = i.mbid""",
    ),
    ("run_artist_pkey", "ALTER TABLE run_artist ADD PRIMARY KEY (mbid)"),
    ("run_artist_uuid_index", "CREATE UNIQUE INDEX ON run_artist (uuid)"),
    ("analyze_run_artist", "ANALYZE run_artist"),
    (
        "upsert_albums",
        """INSERT INTO grow_album
        (uuid, created_on, name, user_id, year, musicbrainz_release_group_id, primary_type, secondary_types)
    SELECT gen_random_uuid(), now(), title, %(user)s, year, mbid, primary_type, secondary_types
    FROM release_group_import ORDER BY mbid
    ON CONFLICT (musicbrainz_release_group_id) DO UPDATE SET
        name = EXCLUDED.name, year = EXCLUDED.year, primary_type = EXCLUDED.primary_type,
        secondary_types = EXCLUDED.secondary_types, updated_on = now()
    WHERE (grow_album.name, grow_album.year, grow_album.primary_type, grow_album.secondary_types) IS DISTINCT FROM
        (EXCLUDED.name, EXCLUDED.year, EXCLUDED.primary_type, EXCLUDED.secondary_types)""",
    ),
    (
        "run_album",
        """CREATE TEMP TABLE run_album AS
    SELECT i.mbid, a.uuid FROM release_group_import i JOIN grow_album a ON a.musicbrainz_release_group_id = i.mbid""",
    ),
    ("run_album_pkey", "ALTER TABLE run_album ADD PRIMARY KEY (mbid)"),
    ("analyze_run_album", "ANALYZE run_album"),
]

# Child rows are diffed against the desired set, not rewritten: an unchanged re-run deletes and inserts nothing.
DIFF_STEPS = [
    (
        "desired_membership",
        """CREATE TEMP TABLE desired_membership AS
    SELECT DISTINCT g.uuid AS group_id, m.uuid AS member_id, i.begin_year, i.end_year, i.ended, i.roles
    FROM membership_import i
    JOIN run_artist g ON g.mbid = i.group_mbid
    JOIN grow_artist m ON m.musicbrainz_artist_id = i.member_mbid""",
    ),
    ("analyze_desired_membership", "ANALYZE desired_membership"),
    (
        "delete_memberships",
        """DELETE FROM grow_artist_membership m USING run_artist r
    WHERE m.group_id = r.uuid AND NOT EXISTS (
        SELECT 1 FROM desired_membership d
        WHERE d.group_id = m.group_id AND d.member_id = m.member_id
            AND d.begin_year IS NOT DISTINCT FROM m.begin_year AND d.end_year IS NOT DISTINCT FROM m.end_year
            AND d.ended IS NOT DISTINCT FROM m.ended AND d.roles IS NOT DISTINCT FROM m.roles
    )""",
    ),
    (
        "insert_memberships",
        """INSERT INTO grow_artist_membership (group_id, member_id, begin_year, end_year, ended, roles)
    SELECT d.group_id, d.member_id, d.begin_year, d.end_year, d.ended, d.roles FROM desired_membership d
    WHERE NOT EXISTS (
        SELECT 1 FROM grow_artist_membership m
        WHERE m.group_id = d.group_id AND m.member_id = d.member_id
            AND m.begin_year IS NOT DISTINCT FROM d.begin_year AND m.end_year IS NOT DISTINCT FROM d.end_year
            AND m.ended IS NOT DISTINCT FROM d.ended AND m.roles IS NOT DISTINCT FROM d.roles
    )
    ORDER BY d.group_id, d.member_id""",
    ),
    (
        "desired_link",
        """CREATE TEMP TABLE desired_link AS
    SELECT r.uuid AS artist_id, l.kind, l.url FROM link_import l JOIN run_artist r ON r.mbid = l.artist_mbid""",
    ),
    ("analyze_desired_link", "ANALYZE desired_link"),
    (
        "delete_links",
        """DELETE FROM grow_artist_link l USING run_artist r
    WHERE l.artist_id = r.uuid AND NOT EXISTS (
        SELECT 1 FROM desired_link d WHERE d.artist_id = l.artist_id AND d.kind = l.kind AND d.url = l.url
    )""",
    ),
    (
        "insert_links",
        """INSERT INTO grow_artist_link (artist_id, kind, url)
    SELECT d.artist_id, d.kind, d.url FROM desired_link d
    WHERE NOT EXISTS (
        SELECT 1 FROM grow_artist_link l WHERE l.artist_id = d.artist_id AND l.kind = d.kind AND l.url = d.url
    )
    ORDER BY d.artist_id, d.kind, d.url""",
    ),
    (
        "desired_alias",
        """CREATE TEMP TABLE desired_alias AS
    SELECT r.uuid AS artist_id, a.name FROM alias_import a JOIN run_artist r ON r.mbid = a.artist_mbid""",
    ),
    ("analyze_desired_alias", "ANALYZE desired_alias"),
    (
        "delete_aliases",
        """DELETE FROM grow_artist_alias l USING run_artist r
    WHERE l.artist_id = r.uuid AND NOT EXISTS (
        SELECT 1 FROM desired_alias d WHERE d.artist_id = l.artist_id AND d.name = l.name
    )""",
    ),
    (
        "insert_aliases",
        """INSERT INTO grow_artist_alias (artist_id, name)
    SELECT d.artist_id, d.name FROM desired_alias d
    WHERE NOT EXISTS (SELECT 1 FROM grow_artist_alias l WHERE l.artist_id = d.artist_id AND l.name = d.name)
    ORDER BY d.artist_id, d.name""",
    ),
    (
        "desired_album_artist",
        """CREATE TEMP TABLE desired_album_artist AS
    SELECT al.uuid AS album_id, r.uuid AS artist_id FROM credit_import c
    JOIN run_album al ON al.mbid = c.release_group_mbid
    JOIN run_artist r ON r.mbid = c.artist_mbid""",
    ),
    ("analyze_desired_album_artist", "ANALYZE desired_album_artist"),
    (
        "delete_album_artists",
        """DELETE FROM grow_album_album_artists aa USING run_artist r, grow_album al
    WHERE aa.artist_id = r.uuid AND al.uuid = aa.album_id AND al.musicbrainz_release_group_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM desired_album_artist d WHERE d.album_id = aa.album_id AND d.artist_id = aa.artist_id)""",
    ),
    (
        "insert_album_artists",
        """INSERT INTO grow_album_album_artists (album_id, artist_id)
    SELECT d.album_id, d.artist_id FROM desired_album_artist d
    WHERE NOT EXISTS (
        SELECT 1 FROM grow_album_album_artists x WHERE x.album_id = d.album_id AND x.artist_id = d.artist_id
    )
    ORDER BY d.album_id, d.artist_id""",
    ),
]


def _stale_steps(user_id: int | None, delta: bool) -> list[tuple[str, str]]:
    # `user_id = NULL` never matches and `IS NOT DISTINCT FROM` can't use the user_id index, so the owner filter is
    # picked here.
    owner = "a.user_id IS NULL" if user_id is None else "a.user_id = %(user)s"
    missing = (
        "a.musicbrainz_artist_id IN (SELECT musicbrainz_id FROM grow_bulk_import_deletion WHERE run_id = %(run)s)"
        if delta
        else "NOT EXISTS (SELECT 1 FROM run_artist r WHERE r.uuid = a.uuid)"
    )
    return [
        # The artists import owns the reference artists' lifecycle: one missing from the run goes once no track or
        # hand-made (non release-group) album credits it.
        (
            "stale_artist",
            f"""CREATE TEMP TABLE stale_artist AS
    SELECT a.uuid FROM grow_artist a
    WHERE {owner} AND {missing}
        AND NOT EXISTS (SELECT 1 FROM the_music_tree_genre_kit_track_artists ta WHERE ta.artist_id = a.uuid)
        AND NOT EXISTS (
            SELECT 1 FROM grow_album_album_artists aa JOIN grow_album al ON al.uuid = aa.album_id
            WHERE aa.artist_id = a.uuid AND al.musicbrainz_release_group_id IS NULL
        )""",
        ),
        ("stale_artist_pkey", "ALTER TABLE stale_artist ADD PRIMARY KEY (uuid)"),
        ("analyze_stale_artist", "ANALYZE stale_artist"),
        (
            "delete_stale_group_memberships",
            "DELETE FROM grow_artist_membership m USING stale_artist s WHERE m.group_id = s.uuid",
        ),
        (
            "delete_stale_member_memberships",
            "DELETE FROM grow_artist_membership m USING stale_artist s WHERE m.member_id = s.uuid",
        ),
        ("delete_stale_links", "DELETE FROM grow_artist_link l USING stale_artist s WHERE l.artist_id = s.uuid"),
        ("delete_stale_aliases", "DELETE FROM grow_artist_alias l USING stale_artist s WHERE l.artist_id = s.uuid"),
        (
            "delete_stale_album_artists",
            "DELETE FROM grow_album_album_artists aa USING stale_artist s WHERE aa.artist_id = s.uuid",
        ),
        ("delete_stale_artists", "DELETE FROM grow_artist a USING stale_artist s WHERE a.uuid = s.uuid"),
        (
            "delete_orphan_albums",
            """DELETE FROM grow_album al WHERE al.musicbrainz_release_group_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM grow_album_album_artists aa WHERE aa.album_id = al.uuid)
        AND NOT EXISTS (SELECT 1 FROM the_music_tree_genre_kit_track t WHERE t.album_id = al.uuid)""",
        ),
    ]


def merge_artist_import_run(run_id: int, user_id: int | None, record: bool) -> dict[str, int]:
    """
    Merges a committed run's staged artists in one transaction: artists upserted on MBID with their details, their
    memberships, links, aliases and release-group albums (with album artists) diffed against the run, and every artist missing
    from the run (a `delta` run: only the artists it lists) deleted once nothing credits it. Run after the songs import so
    song artists already carry their MBID.
    """
    with hold_merge_lock(run_id):
        try:
            result = _merge(run_id, {"run": run_id, "user": user_id}, record)
            invalidate_search_cache()
            return result
        finally:
            # A failed merge rolls back, so its staged rows are dropped here instead of lingering until the next run.
            ArtistImportStaging.objects.filter(run_id=run_id).delete()
            BulkImportDeletion.objects.filter(run_id=run_id).delete()
            BulkImportRun.objects.filter(pk=run_id).delete()


def _merge(run_id: int, params: dict, record: bool) -> dict[str, int]:
    delta = BulkImportRun.objects.get(pk=run_id).mode == BulkImportRun.Mode.DELTA
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {TEMP_TABLES}")
        cursor.execute("SELECT EXISTS (SELECT 1 FROM grow_artist_import_staging WHERE run_id = %(run)s)", params)
        if not delta and not cursor.fetchone()[0]:
            # Artists missing from the run are deleted, so an empty run would wipe every uncredited artist.
            raise ValueError(f"import run {run_id} has no staged artists")
        run_steps(cursor, [*EXPANDED_STEPS, *RESOLVE_STEPS, *DIFF_STEPS, *_stale_steps(params["user"], delta)], params)
        cursor.execute("SELECT count(*) FROM run_artist")
        (imported,) = cursor.fetchone()
        cursor.execute(f"DROP TABLE IF EXISTS {TEMP_TABLES}")
        if record:
            ImportRun.objects.create(kind=ImportRun.Kind.ARTISTS, count=imported, skipped_count=0)
    return {"imported": imported, "skipped": 0}
