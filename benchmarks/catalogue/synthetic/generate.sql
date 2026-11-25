-- Synthetic Grow catalogue calibrated on staging aggregates (profile.json, 2026-11-21), for the catalogue benchmark
-- (#511). Run with psql against a migrated schema: -v songs=N -v artists=N -v albums=N -v genres=6133 -v tagged_genres=N -v rel_stride=N
-- (genres must be 6133: the graph level sizes are tuned for it).
-- Same seed and variables give the same rows. Skews follow profile.json: songs per artist (largest artist about 0.45% of songs),
-- largest genre about 4.7% of the genre-tagged tracks, 49% of tracks without a genre.
\set ON_ERROR_STOP on
BEGIN;
SELECT setseed(0.511);

-- Criteria type 0 is genre (seeded by migration 0002); the reference-genre constraint requires it.
SELECT :genres = 6133 AS genres_ok \gset
\if :genres_ok
\else
  \echo 'generate.sql: genres must be 6133 (graph level sizes are tuned for it)'
  SELECT 1 / 0;
\endif

INSERT INTO grow_artist (uuid, name, created_on, ended, recording_count, musicbrainz_artist_id, country, begin_year)
SELECT md5('a' || i)::uuid, 'Artist ' || i, now(), false, 0, md5('ma' || i)::uuid,
       (ARRAY['US', 'GB', 'FR', 'DE', 'JP', 'BR'])[1 + i % 6], (1900 + i % 120)::smallint
FROM generate_series(1, :artists) AS i;

INSERT INTO grow_album (uuid, name, created_on, secondary_types, musicbrainz_release_group_id, primary_type, year)
SELECT md5('al' || i)::uuid, 'Album ' || i, now(), '[]'::jsonb, md5('mal' || i)::uuid, 'Album', (1950 + i % 75)::text
FROM generate_series(1, :albums) AS i;

INSERT INTO grow_album_album_artists (album_id, artist_id)
SELECT md5('al' || i)::uuid, md5('a' || (1 + i % :artists))::uuid FROM generate_series(1, :albums) AS i
UNION ALL
SELECT md5('al' || i)::uuid, md5('a' || (1 + (i * 7 + 3) % :artists))::uuid
FROM generate_series(1, :albums) AS i WHERE i % 6 = 0 AND (i * 7 + 3) % :artists <> i % :artists;

-- Genre graph: node 1 is the root and nodes are laid out in levels whose sizes (a share of the node count, tuned so the
-- depth and the lineage row count match staging) sum to :genres. A node hangs under a node of the level above, drawn
-- with a power skew that gives the wide hubs; the level-2 nodes get a stronger skew so one branch holds most of the
-- tree, as staging does. A flat power law over all earlier nodes cannot reach depth 8 with at most 94 children.
CREATE TEMP TABLE synthetic_genre_level AS
WITH share (lvl, n, skew) AS (VALUES (0, 1, 1.0), (1, 15, 2.3), (2, 200, 6.0), (3, 1000, 2.3), (4, 1950, 2.3),
                                     (5, 1700, 2.3), (6, 900, 2.3), (7, 300, 2.3), (8, 67, 2.3))
SELECT lvl, skew, CASE WHEN lvl = 8 THEN :genres - SUM(n) OVER (ORDER BY lvl ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
                       ELSE round(n * :genres / 6133.0) END AS n
FROM share;
CREATE TEMP TABLE synthetic_genre_range AS
SELECT lvl, skew, n, COALESCE(SUM(n) OVER (ORDER BY lvl ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS first_id
FROM synthetic_genre_level;
CREATE TEMP TABLE synthetic_genre_parent AS
SELECT i, CASE WHEN r.lvl = 0 THEN NULL
               ELSE (pr.first_id + 1 + floor(pr.n * power(random(), r.skew)))::int END AS parent
FROM generate_series(1, :genres) AS i
JOIN synthetic_genre_range r ON i > r.first_id AND i <= r.first_id + r.n
LEFT JOIN synthetic_genre_range pr ON pr.lvl = r.lvl - 1;

INSERT INTO grow_criteria (uuid, created_on, name, parent_id, root_id, type_id, tree_name)
SELECT md5('g' || i)::uuid, now(), 'Genre ' || i, CASE WHEN parent IS NULL THEN NULL ELSE md5('g' || parent)::uuid END,
       md5('g1')::uuid, 0, 'genre'
FROM synthetic_genre_parent;

INSERT INTO grow_genre (criteria_ptr_id, is_excluded, is_manually_edited, source, has_name_conflict, is_unaccepted_root,
                        is_umbrella)
SELECT md5('g' || i)::uuid, false, false, 'pipeline', false, false, false FROM synthetic_genre_parent;

INSERT INTO grow_criteria_lineage_rel (created_on, degree, ascendant_id, descendant_id)
WITH RECURSIVE up (descendant, ascendant, degree) AS (
    SELECT i, i, 0 FROM synthetic_genre_parent
    UNION ALL
    SELECT up.descendant, p.parent, up.degree + 1
    FROM up JOIN synthetic_genre_parent p ON p.i = up.ascendant WHERE p.parent IS NOT NULL
)
SELECT now(), degree, md5('g' || ascendant)::uuid, md5('g' || descendant)::uuid FROM up;

INSERT INTO the_music_tree_genre_kit_playlist (uuid, created_on, play_count)
SELECT md5('p' || i)::uuid, now(), 0 FROM generate_series(1, :genres) AS i;

INSERT INTO grow_criteria_playlist (playlist_id, criteria_id, type_id, views_count)
SELECT md5('p' || i)::uuid, md5('g' || i)::uuid, 0, 0 FROM generate_series(1, :genres) AS i;

-- Tracks: 49% have no genre. The others are split between the first :tagged_genres genres by a quota curve that
-- interpolates, in log-log, the staging quantiles of tracks per genre (rank fraction -> tracks: 0.001 -> 753109,
-- 0.01 -> 170444, 0.1 -> 18153, 0.5 -> 755, 1 -> 1; profile.json). A track draws its genre from the quota CDF.
CREATE TEMP TABLE synthetic_curve (x double precision, c double precision);
INSERT INTO synthetic_curve VALUES (0.0006, 755887), (0.001, 753109), (0.01, 170444), (0.1, 18153), (0.5, 755),
                                   (1, 1);
CREATE TEMP TABLE synthetic_quota AS
WITH rk AS (SELECT r, r::double precision / :tagged_genres AS x FROM generate_series(1, :tagged_genres) AS r),
     seg AS (SELECT x AS x0, c AS c0, lead(x) OVER (ORDER BY x) AS x1, lead(c) OVER (ORDER BY x) AS c1
             FROM synthetic_curve),
     w AS (SELECT r, exp(ln(c0) + (ln(greatest(x, x0)) - ln(x0)) * (ln(c1) - ln(c0)) / (ln(x1) - ln(x0))) AS weight
           FROM rk JOIN seg ON rk.x >= seg.x0 AND rk.x < seg.x1 OR (rk.x = 1 AND seg.x1 = 1))
SELECT r, sum(weight) OVER (ORDER BY r) / sum(weight) OVER () AS cdf FROM w;
CREATE INDEX ON synthetic_quota (cdf);

CREATE TEMP TABLE synthetic_track_genre AS
SELECT i, CASE WHEN u1 < 0.49 THEN NULL
               ELSE (SELECT r FROM synthetic_quota WHERE cdf >= u2 ORDER BY cdf LIMIT 1) END AS genre
FROM (SELECT i, random() AS u1, random() AS u2 FROM generate_series(1, :songs) AS i) AS d;

INSERT INTO the_music_tree_genre_kit_track (uuid, title, created_on, play_count, album_id, track_number, genre_id)
SELECT md5('t' || i)::uuid, 'Song title ' || md5('title' || i), now(), 0, md5('al' || (1 + i % :albums))::uuid,
       1 + i % 15, CASE WHEN genre IS NOT NULL THEN md5('g' || genre)::uuid END
FROM synthetic_track_genre;

INSERT INTO grow_song (track_id, is_manually_edited, musicbrainz_recording_id, first_release_year, recording_count,
                       youtube_video_id, youtube_view_count, genre_id)
SELECT md5('t' || i)::uuid, false, md5('r' || i)::uuid, (1950 + i % 75)::smallint, 1 + i % 40,
       CASE WHEN i % 10 < 3 THEN substr(md5('yt' || i), 1, 11) END,
       CASE WHEN i % 10 < 3 THEN (i * 37) % 10000000 END,
       CASE WHEN genre IS NOT NULL THEN md5('g' || genre)::uuid END
FROM synthetic_track_genre;

INSERT INTO the_music_tree_genre_kit_track_artists (track_id, artist_id)
SELECT md5('t' || i)::uuid, md5('a' || (1 + floor((:artists - 1) * power(random(), 2.7)))::bigint)::uuid
FROM generate_series(1, :songs) AS i;

-- Playlist membership: tagged tracks only, each in its own genre's playlist. Staging has 653k rels for 31M songs.
INSERT INTO the_music_tree_genre_kit_track_playlist_rel (created_on, position, playlist_id, track_id, genre_id)
SELECT now(), row_number() OVER (PARTITION BY genre ORDER BY i), md5('p' || genre)::uuid, md5('t' || i)::uuid,
       md5('g' || genre)::uuid
FROM synthetic_track_genre WHERE genre IS NOT NULL AND i % :rel_stride = 0;

UPDATE grow_artist a SET recording_count = c.n
FROM (SELECT artist_id, count(*) AS n FROM the_music_tree_genre_kit_track_artists GROUP BY artist_id) c
WHERE a.uuid = c.artist_id;
COMMIT;
