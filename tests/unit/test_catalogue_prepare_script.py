"""Approved preparation script: step order, fail-fast, and the planner-statistics gate."""

from unittest.mock import MagicMock, patch

import pytest

from benchmarks.catalogue import prepare


def run_main(failing=None):
    calls = []
    arguments_seen = {}

    def call_command(command, *arguments):
        calls.append(command)
        arguments_seen[command] = arguments
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
    return calls, error, arguments_seen


def test_derivation_check_runs_before_rebuilds_and_repairs_after():
    calls, error, _ = run_main()
    assert error is None
    assert calls == [
        "migrate",
        "verify_song_membership",
        "rebuild_song_search",
        "rebuild_artist_song",
        "verify_genre_membership_counts",
        "verify_genre_catalogue_counts",
        "vacuum",
    ]


def test_flags_are_passed_so_an_old_image_fails_fast():
    _, _, arguments_seen = run_main()
    assert arguments_seen["migrate"] == ("--no-input",)
    assert arguments_seen["rebuild_song_search"] == ("--if-stale",)
    assert arguments_seen["rebuild_artist_song"] == ("--if-stale",)
    assert arguments_seen["verify_genre_membership_counts"] == ("--repair",)
    assert arguments_seen["verify_genre_catalogue_counts"] == ("--repair",)


def test_drifted_membership_stops_before_any_rebuild():
    calls, error, _ = run_main(failing="verify_song_membership")
    assert error is not None
    assert calls == ["migrate", "verify_song_membership"]


def test_tables_without_statistics_fail_the_preparation():
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[("grow_song",)], [("grow_song",)]]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    with (
        patch.dict(prepare.__dict__, {"connection": connection}),
        patch.object(prepare, "log"),
        pytest.raises(SystemExit) as raised,
    ):
        prepare.vacuum_analyze()
    assert "grow_song" in str(raised.value)


def test_postgres_16_is_accepted():
    connection = MagicMock(vendor="postgresql")
    connection.cursor.return_value.connection.info.server_version = 160004
    with patch.dict(prepare.__dict__, {"connection": connection}):
        prepare.require_postgres()


def test_other_postgres_major_is_refused():
    connection = MagicMock(vendor="postgresql")
    connection.cursor.return_value.connection.info.server_version = 150004
    with patch.dict(prepare.__dict__, {"connection": connection}), pytest.raises(SystemExit):
        prepare.require_postgres()
