"""Shape and determinism of the synthetic catalogue generator (needs a migrated, empty PostgreSQL database)."""

import json
import os
import subprocess
import unittest
from pathlib import Path

SYNTHETIC = Path(__file__).resolve().parents[1] / "synthetic"
PROFILE = json.loads((SYNTHETIC / "profile.json").read_text())
URL = os.environ.get("GROW_SYNTHETIC_DATABASE_URL")
DIVISOR = 1000
TOLERANCE = 1.5
ROOTS = "grow_artist, grow_album, grow_criteria, the_music_tree_genre_kit_playlist, the_music_tree_genre_kit_track"

FINGERPRINT_SQL = """
SELECT md5(concat_ws('|',
  (SELECT string_agg(parent_id::text, ',' ORDER BY uuid) FROM grow_criteria),
  (SELECT string_agg(genre_id::text, ',' ORDER BY uuid) FROM the_music_tree_genre_kit_track),
  (SELECT string_agg(artist_id::text, ',' ORDER BY track_id, artist_id) FROM the_music_tree_genre_kit_track_artists)))
"""

SHAPE_SQL = """
SELECT json_build_object(
  'tracks', (SELECT count(*) FROM the_music_tree_genre_kit_track),
  'untagged', (SELECT count(*) FROM the_music_tree_genre_kit_track WHERE genre_id IS NULL),
  'top_genre', (SELECT max(c) FROM (SELECT count(*) c FROM the_music_tree_genre_kit_track
                                    WHERE genre_id IS NOT NULL GROUP BY genre_id) t),
  'top_artist', (SELECT max(c) FROM (SELECT count(*) c FROM the_music_tree_genre_kit_track_artists
                                     GROUP BY artist_id) t),
  'depth', (SELECT max(degree) FROM grow_criteria_lineage_rel),
  'lineage', (SELECT count(*) FROM grow_criteria_lineage_rel),
  'children_max', (SELECT max(c) FROM (SELECT count(*) c FROM grow_criteria GROUP BY parent_id) t
                   WHERE c IS NOT NULL)
)
"""


def psql(sql):
    return subprocess.run(
        ["psql", URL, "-q", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql], check=True, capture_output=True, text=True
    ).stdout.strip()


def generate():
    psql(f"TRUNCATE {ROOTS} CASCADE")
    subprocess.run(["bash", str(SYNTHETIC / "generate.sh"), URL, str(DIVISOR)], check=True, capture_output=True)


@unittest.skipUnless(URL, "set GROW_SYNTHETIC_DATABASE_URL to a migrated empty PostgreSQL database")
class SyntheticCatalogueTest(unittest.TestCase):
    def within(self, actual, expected, name):
        self.assertTrue(expected / TOLERANCE <= actual <= expected * TOLERANCE, f"{name}: {actual} vs {expected}")

    def test_shape_follows_the_staging_profile_and_is_deterministic(self):
        generate()
        first = psql(FINGERPRINT_SQL)
        shape = json.loads(psql(SHAPE_SQL))
        generate()
        self.assertEqual(first, psql(FINGERPRINT_SQL))

        graph = PROFILE["genre_graph"]
        self.assertAlmostEqual(shape["untagged"] / shape["tracks"], PROFILE["tracks_per_genre"]["untagged_fraction"], 1)
        # Genre count is not scaled, so the genre-side shares and the graph compare directly with staging.
        tagged = shape["tracks"] - shape["untagged"]
        self.within(
            shape["top_genre"] / tagged,
            PROFILE["tracks_per_genre"]["max"] / PROFILE["tracks_per_genre"]["tagged_tracks"],
            "top genre share",
        )
        self.within(shape["depth"], graph["max_depth"], "graph depth")
        self.within(shape["lineage"], PROFILE["rows"]["lineage_rel"], "lineage rows")
        self.assertLessEqual(shape["children_max"], graph["children_max"] * TOLERANCE)
        # The top artist share depends on the artist count (draw u**2.7 over N artists), so check the closed form
        # at this scale; the staging value itself is checked at full scale by the fidelity run.
        artists = PROFILE["rows"]["artist"] // DIVISOR
        self.within(shape["top_artist"], shape["tracks"] * artists ** (-1 / 2.7), "top artist songs")


if __name__ == "__main__":
    unittest.main()
