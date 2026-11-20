"""Approved preparation script: step order, fail-fast, and the planner-statistics gate."""

import unittest
from unittest.mock import MagicMock, patch

from benchmarks.catalogue import prepare


def run_main(failing=None):
    calls = []

    def call_command(command, *arguments):
        calls.append(command)
        if command == failing:
            raise RuntimeError(f"{command} failed")

    with (
        patch.object(prepare, "call_command", call_command),
        patch.object(prepare.django, "setup"),
        patch.object(prepare, "require_postgres"),
        patch.dict(prepare.__dict__, {"connection": MagicMock()}),
        patch.object(prepare, "vacuum_analyze", lambda: calls.append("vacuum")),
        patch.object(prepare, "log"),
    ):
        try:
            prepare.main()
            error = None
        except RuntimeError as exc:
            error = exc
    return calls, error


class PrepareTests(unittest.TestCase):
    def test_derivation_check_runs_before_rebuilds_and_repairs_after(self):
        calls, error = run_main()
        self.assertIsNone(error)
        self.assertEqual(
            calls,
            [
                "migrate",
                "verify_song_membership",
                "rebuild_song_search",
                "rebuild_artist_song",
                "verify_genre_membership_counts",
                "verify_genre_catalogue_counts",
                "vacuum",
            ],
        )

    def test_drifted_membership_stops_before_any_rebuild(self):
        calls, error = run_main(failing="verify_song_membership")
        self.assertIsNotNone(error)
        self.assertEqual(calls, ["migrate", "verify_song_membership"])

    def test_tables_without_statistics_fail_the_preparation(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [[("grow_song",)], [("grow_song",)]]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        with (
            patch.dict(prepare.__dict__, {"connection": connection}),
            patch.object(prepare, "log"),
            self.assertRaises(SystemExit) as raised,
        ):
            prepare.vacuum_analyze()
        self.assertIn("grow_song", str(raised.exception))

    def test_other_postgres_major_is_refused(self):
        connection = MagicMock(vendor="postgresql")
        connection.cursor.return_value.connection.info.server_version = 150004
        with patch.dict(prepare.__dict__, {"connection": connection}), self.assertRaises(SystemExit):
            prepare.require_postgres()


if __name__ == "__main__":
    unittest.main()
