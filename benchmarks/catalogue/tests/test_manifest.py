"""Offline safety contracts for the benchmark manifest and sanitization policy."""

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks.catalogue.manifest import Session, trusted_json
from benchmarks.catalogue.sanitization import Policy


def manifest():
    return {
        "version": 1,
        "repository": "BehindTheMusicTree/grow-the-music-tree-api",
        "pull_request": 500,
        "base": {"sha": "a" * 40, "image": "ghcr.io/behindthemusictree/grow@sha256:" + "1" * 64},
        "head": {"sha": "b" * 40, "image": "ghcr.io/behindthemusictree/grow@sha256:" + "2" * 64},
        "backup_sha256": "3" * 64,
        "scenario_sha256": "4" * 64,
        "rounds": 4,
    }


def policy():
    return {
        "version": 1,
        "schema_sha256": hashlib.sha256(b"reviewed schema").hexdigest(),
        "tables": {
            "grow_song": {"columns": ["track_id"], "null_columns": [], "minimum_rows": 30_000_000},
            "the_music_tree_genre_kit_track": {
                "columns": ["uuid", "title", "user_id"],
                "null_columns": ["user_id"],
                "minimum_rows": 30_000_000,
            },
        },
    }


class ManifestTest(unittest.TestCase):
    def test_round_trip_and_alternating_rounds(self):
        session = Session.parse(manifest())
        self.assertEqual(session.as_dict(), manifest())
        self.assertEqual(
            session.schedule(),
            [
                ("base", 1),
                ("head", 1),
                ("head", 2),
                ("base", 2),
                ("base", 3),
                ("head", 3),
                ("head", 4),
                ("base", 4),
            ],
        )

    def test_every_input_is_bound_to_identity(self):
        original = manifest()
        identity = Session.parse(original).identity
        for key, replacement in (
            ("pull_request", 501),
            ("rounds", 6),
            ("backup_sha256", "f" * 64),
            ("scenario_sha256", "e" * 64),
            ("base", original["head"]),
            ("head", original["base"]),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed[key] = replacement
                self.assertNotEqual(Session.parse(changed).identity, identity)

    def test_mutable_or_unrelated_images_and_abbreviated_shas_refused(self):
        for field, replacement in (
            ("image", "ghcr.io/behindthemusictree/grow:latest"),
            ("image", "ghcr.io/attacker/grow@sha256:" + "a" * 64),
            ("sha", "abcdef1"),
            ("sha", "a" * 40 + "\n"),
        ):
            raw = manifest()
            raw["head"][field] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                Session.parse(raw)

    def test_missing_unknown_and_invalid_fields_refused(self):
        for mutation in (
            lambda x: x.pop("head"),
            lambda x: x.update(command="sh"),
            lambda x: x.update(rounds=True),
            lambda x: x.update(rounds=0),
            lambda x: x.update(repository="attacker/grow"),
            lambda x: x.update(version=True),
        ):
            raw = manifest()
            mutation(raw)
            with self.assertRaises(ValueError):
                Session.parse(raw)

    def test_untrusted_manifest_path_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text("{}")
            symlink = Path(directory) / "link.json"
            symlink.symlink_to(path)
            with self.assertRaises(ValueError):
                trusted_json(symlink)
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                trusted_json(path)


class SanitizationTest(unittest.TestCase):
    def setUp(self):
        self.policy = Policy.parse(policy())

    def test_only_approved_table_data_selected(self):
        toc = "\n".join(
            [
                "; archive comment",
                "1; 0 0 TABLE DATA public auth_user postgres",
                "2; 0 0 TABLE DATA public grow_song postgres",
                "3; 0 0 TABLE DATA public the_music_tree_genre_kit_track postgres",
                "4; 0 0 TABLE DATA public grow_history_entry postgres",
                "5; 0 0 BLOBS - BLOBS postgres",
                "6; 0 0 MATERIALIZED VIEW DATA public secrets postgres",
                "7; 0 0 SEQUENCE SET public auth_user_id_seq postgres",
            ]
        )
        self.assertEqual(
            self.policy.data_toc(toc),
            "2; 0 0 TABLE DATA public grow_song postgres\n"
            "3; 0 0 TABLE DATA public the_music_tree_genre_kit_track postgres\n",
        )

    def test_missing_duplicate_and_unsupported_toc_refused(self):
        song = "2; 0 0 TABLE DATA public grow_song postgres\n"
        track = "3; 0 0 TABLE DATA public the_music_tree_genre_kit_track postgres\n"
        for toc in (song, song + song + track, song.replace("public", "private") + track):
            with self.assertRaises(ValueError):
                self.policy.data_toc(toc)

    def test_schema_and_columns_must_match_review(self):
        columns = {name: table["columns"] for name, table in policy()["tables"].items()}
        self.policy.verify_schema(b"reviewed schema", columns)
        with self.assertRaises(ValueError):
            self.policy.verify_schema(b"changed schema", columns)
        columns["grow_song"].append("new_private_payload")
        with self.assertRaises(ValueError):
            self.policy.verify_schema(b"reviewed schema", columns)

    def test_private_and_operational_tables_cannot_be_approved(self):
        for name in (
            "auth_user",
            "grow_history_entry",
            "grow_user_profile",
            "django_q_ormq",
            "grow_song_import_staging",
            "grow_genre_tree_import_payload",
        ):
            raw = policy()
            raw["tables"][name] = raw["tables"]["grow_song"]
            with self.subTest(name=name), self.assertRaises(ValueError):
                Policy.parse(raw)

    def test_ownership_check_required_and_column_injection_refused(self):
        for columns, nulls in ((["uuid", "user_id"], []), (["uuid", 'x"; DROP TABLE grow_song; --'], [])):
            raw = policy()
            raw["tables"]["grow_song"].update(columns=columns, null_columns=nulls)
            with self.assertRaises(ValueError):
                Policy.parse(raw)

    def test_incomplete_private_or_unverified_data_refused(self):
        good_counts = {"grow_song": 32_000_000, "the_music_tree_genre_kit_track": 32_000_000, "auth_user": 0}
        good_nulls = {"grow_song": {}, "the_music_tree_genre_kit_track": {"user_id": 0}}
        self.policy.verify_rows(good_counts, good_nulls)
        for counts, nulls in (
            (dict(good_counts, auth_user=1), good_nulls),
            (dict(good_counts, grow_song=9000), good_nulls),
            (good_counts, {}),
            (good_counts, dict(good_nulls, the_music_tree_genre_kit_track={"user_id": 1})),
        ):
            with self.assertRaises(ValueError):
                self.policy.verify_rows(counts, nulls)

    def test_tiny_catalogue_policy_refused(self):
        raw = policy()
        raw["tables"]["grow_song"]["minimum_rows"] = 9000
        with self.assertRaises(ValueError):
            Policy.parse(raw)


if __name__ == "__main__":
    unittest.main()
