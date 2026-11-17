"""Throwaway feasibility spike: synthetic production-shaped catalogue bundle.

Never merged. Produces pre-data.sql, post-data.sql and generation SQL from the
reviewed column inventory, with no production data.
"""

import re
import sys
from pathlib import Path

from ..catalogue_restore import EMPTY, RETAIN, TRACK, inventory

CATALOGUE = Path(__file__).resolve().parent.parent


def tables() -> dict:
    return inventory((CATALOGUE / "catalogue-schema.tsv").read_text())


def pre_data() -> str:
    lines = []
    for name, columns in tables().items():
        body = ",\n  ".join(f'"{c}" {t}{" NOT NULL" if n == "NO" else ""}' for c, t, n in columns)
        lines.append(f'CREATE TABLE public."{name}" (\n  {body}\n);')
    return "\n".join(lines) + "\n"


def primary_key(name: str, columns: list) -> str | None:
    names = [c[0] for c in columns]
    for key in ("uuid", "id", "track_id", "criteria_ptr_id", "playlist_id", "item_id"):
        if key in names:
            return key
    return None


def post_data() -> str:
    t = tables()
    statements = []
    for name in sorted(RETAIN):
        key = primary_key(name, t[name])
        if key:
            statements.append(f'ALTER TABLE ONLY public."{name}" ADD CONSTRAINT "{name}_pkey" PRIMARY KEY ("{key}");')
    song, rel, artists = "grow_song", f"{TRACK}_playlist_rel", f"{TRACK}_artists"
    indexes = [
        (TRACK, "album_id"),
        (TRACK, "genre_id"),
        (TRACK, "title"),
        (song, "musicbrainz_recording_id"),
        (song, "youtube_video_id"),
        (artists, "track_id"),
        (artists, "artist_id"),
        (rel, "track_id"),
        (rel, "playlist_id, position"),
        ("grow_artist", "musicbrainz_artist_id"),
        ("grow_artist", "folded_name"),
        ("grow_album", "musicbrainz_release_group_id"),
        ("grow_album_album_artists", "album_id"),
        ("grow_album_album_artists", "artist_id"),
        ("grow_criteria", "parent_id"),
        ("grow_criteria_lineage_rel", "ascendant_id"),
        ("grow_criteria_lineage_rel", "descendant_id"),
    ]
    for table, cols in indexes:
        label = re.sub(r"\W+", "_", cols)
        quoted = ", ".join(f'"{c.strip()}"' for c in cols.split(","))
        statements.append(f'CREATE INDEX "{table}_{label}_idx" ON public."{table}" ({quoted});')
    foreign = [
        (TRACK, "album_id", "grow_album", "uuid"),
        (TRACK, "genre_id", "grow_criteria", "uuid"),
        (song, "track_id", TRACK, "uuid"),
        (artists, "track_id", TRACK, "uuid"),
        (artists, "artist_id", "grow_artist", "uuid"),
        (rel, "track_id", TRACK, "uuid"),
        (rel, "playlist_id", f"{TRACK.replace('track', 'playlist')}", "uuid"),
    ]
    for table, column, target, key in foreign:
        statements.append(
            f'ALTER TABLE ONLY public."{table}" ADD CONSTRAINT "{table}_{column}_fk" '
            f'FOREIGN KEY ("{column}") REFERENCES public."{target}"("{key}");'
        )
    return "\n".join(statements) + "\n"


def generation_sql(songs: int, chunk: int = 4_000_000) -> str:
    """Server-side INSERT..SELECT; every row is NULL-owned and fully referenced."""
    genres = 20_000
    albums, artists = songs // 5, songs // 10
    u = lambda expr: f"md5('{{}}' || ({expr})::text)::uuid"  # noqa: E731
    pl = TRACK.replace("track", "playlist")
    out = [
        "SET synchronous_commit = off;",
        f"INSERT INTO public.{TRACK.replace('track', 'criteriatype')} (id, label) SELECT g, 'type' || g FROM generate_series(1, 5) g;",
        # criteria / genre / playlist tree
        "INSERT INTO public.grow_criteria (uuid, created_on, name, root_id, type_id, tree_name, folded_name, parent_id, summary) "
        f"SELECT {u('g').format('c')}, now(), 'Genre ' || g, {u('1').format('c')}, 1, 'tree', 'genre ' || g, "
        f"CASE WHEN g = 1 THEN NULL ELSE {u('1 + (g / 8)').format('c')} END, 'Synthetic genre summary ' || repeat('x', 200) "
        f"FROM generate_series(1, {genres}) g;",
        "INSERT INTO public.grow_genre (criteria_ptr_id, is_excluded, is_manually_edited, source, has_name_conflict, is_unaccepted_root, is_umbrella) "
        f"SELECT {u('g').format('c')}, false, false, 'synthetic', false, false, false FROM generate_series(1, {genres}) g;",
        f"INSERT INTO public.{pl} (uuid, created_on, play_count) SELECT {u('g').format('p')}, now(), 0 FROM generate_series(1, {genres}) g;",
        "INSERT INTO public.grow_criteria_playlist (playlist_id, criteria_id, type_id, views_count, direct_songs_count) "
        f"SELECT {u('g').format('p')}, {u('g').format('c')}, 1, 0, 0 FROM generate_series(1, {genres}) g;",
        "INSERT INTO public.grow_criteria_lineage_rel (id, created_on, degree, ascendant_id, descendant_id) "
        f"SELECT g, now(), 1, {u('1 + (g / 8)').format('c')}, {u('g').format('c')} FROM generate_series(2, {genres}) g;",
        "INSERT INTO public.grow_wikidata_item (item_id, label) "
        f"SELECT 'Q' || g, 'Item ' || g FROM generate_series(1, {genres}) g;",
        "INSERT INTO public.grow_artist (uuid, created_on, name, ended, recording_count, musicbrainz_artist_id, folded_name, country, type) "
        f"SELECT {u('g').format('a')}, now(), 'Artist ' || g || ' ' || md5(g::text), false, 10, {u('g').format('ma')}, "
        "'artist ' || g, 'XX', 'Person' "
        f"FROM generate_series(1, {artists}) g;",
        "INSERT INTO public.grow_album (uuid, created_on, name, year, musicbrainz_release_group_id, secondary_types) "
        f"SELECT {u('g').format('al')}, now(), 'Album ' || g || ' ' || md5(g::text), '2000', {u('g').format('mal')}, '[]' "
        f"FROM generate_series(1, {albums}) g;",
        "INSERT INTO public.grow_album_album_artists (id, album_id, artist_id) "
        f"SELECT g, {u('g').format('al')}, {u('1 + (g % ' + str(artists) + ')').format('a')} FROM generate_series(1, {albums}) g;",
    ]
    for start in range(1, songs + 1, chunk):
        stop = min(start + chunk - 1, songs)
        series = f"generate_series({start}, {stop}) g"
        out += [
            f"INSERT INTO public.{TRACK} (uuid, created_on, play_count, title, album_id, genre_id) "
            f"SELECT {u('g').format('t')}, now(), 0, 'Track ' || g || ' ' || md5(g::text), "
            f"{u('1 + (g % ' + str(albums) + ')').format('al')}, {u('1 + (g % ' + str(genres) + ')').format('c')} FROM {series};",
            "INSERT INTO public.grow_song (track_id, is_manually_edited, musicbrainz_recording_id, first_release_year, "
            "youtube_video_id, youtube_view_count, recording_count) "
            f"SELECT {u('g').format('t')}, false, {u('g').format('mr')}, 1990, substr(md5(g::text), 1, 11), g, 1 FROM {series};",
            f"INSERT INTO public.{TRACK}_artists (id, track_id, artist_id) "
            f"SELECT g, {u('g').format('t')}, {u('1 + (g % ' + str(artists) + ')').format('a')} FROM {series};",
            f"INSERT INTO public.{TRACK}_playlist_rel (id, created_on, position, playlist_id, track_id, genre_id) "
            f"SELECT g, now(), g, {u('1 + (g % ' + str(genres) + ')').format('p')}, {u('g').format('t')}, "
            f"{u('1 + (g % ' + str(genres) + ')').format('c')} FROM {series};",
        ]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    directory, songs = Path(sys.argv[1]), int(sys.argv[2])
    directory.mkdir(parents=True, exist_ok=True)
    assert not EMPTY & RETAIN
    (directory / "pre-data.sql").write_text(pre_data())
    (directory / "post-data.sql").write_text(post_data())
    (directory / "generate.sql").write_text(generation_sql(songs))
