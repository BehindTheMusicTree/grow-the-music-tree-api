-- Synthetic catalogue at prod scale for the runner capacity probe (#511 step 0). Loaded into a schema that has only
-- its pre-data section (no indexes, no constraints), like a restore. Row counts mirror staging on 2026-11-19; the
-- song -> artist skew gives one artist ~250k songs, like the largest real artists. Genres, playlists, aliases, links
-- and history are left empty (about 4 GB on staging, mostly the excluded history).
\set ON_ERROR_STOP on
SELECT setseed(0.511);

\echo generate grow_artist
INSERT INTO grow_artist (uuid, name, created_on, ended, recording_count, musicbrainz_artist_id, country,
                         begin_year)
SELECT md5('a' || i)::uuid, 'Artist ' || i, now(), false, 0, md5('ma' || i)::uuid,
       (ARRAY['US', 'GB', 'FR', 'DE', 'JP', 'BR'])[1 + i % 6], (1900 + i % 120)::smallint
FROM generate_series(1, :artists) AS i;

\echo generate grow_album
INSERT INTO grow_album (uuid, name, created_on, secondary_types, musicbrainz_release_group_id, primary_type, year)
SELECT md5('al' || i)::uuid, 'Album ' || i, now(), '[]'::jsonb, md5('mal' || i)::uuid, 'Album', (1950 + i % 75)::text
FROM generate_series(1, :albums) AS i;

\echo generate grow_album_album_artists
INSERT INTO grow_album_album_artists (album_id, artist_id)
SELECT md5('al' || i)::uuid, md5('a' || (1 + i % :artists))::uuid FROM generate_series(1, :albums) AS i
UNION ALL
SELECT md5('al' || i)::uuid, md5('a' || (1 + (i * 7 + 3) % :artists))::uuid
FROM generate_series(1, :albums) AS i WHERE i % 6 = 0 AND (i * 7 + 3) % :artists <> i % :artists;

\echo generate the_music_tree_genre_kit_track
INSERT INTO the_music_tree_genre_kit_track (uuid, title, created_on, play_count, album_id, track_number)
SELECT md5('t' || i)::uuid, 'Song title ' || md5('title' || i), now(), 0, md5('al' || (1 + i % :albums))::uuid,
       1 + i % 15
FROM generate_series(1, :songs) AS i;

\echo generate grow_song
INSERT INTO grow_song (track_id, is_manually_edited, musicbrainz_recording_id, first_release_year, recording_count,
                       youtube_video_id, youtube_view_count)
SELECT md5('t' || i)::uuid, false, md5('r' || i)::uuid, (1950 + i % 75)::smallint, 1 + i % 40,
       CASE WHEN i % 10 < 3 THEN substr(md5('yt' || i), 1, 11) END,
       CASE WHEN i % 10 < 3 THEN (i * 37) % 10000000 END
FROM generate_series(1, :songs) AS i;

\echo generate the_music_tree_genre_kit_track_artists
INSERT INTO the_music_tree_genre_kit_track_artists (track_id, artist_id)
SELECT md5('t' || i)::uuid, md5('a' || (1 + floor((:artists - 1) * power(random(), 3)))::bigint)::uuid
FROM generate_series(1, :songs) AS i;

\echo generate grow_artist.recording_count
UPDATE grow_artist a SET recording_count = c.n
FROM (SELECT artist_id, count(*) AS n FROM the_music_tree_genre_kit_track_artists GROUP BY artist_id) c
WHERE a.uuid = c.artist_id;
