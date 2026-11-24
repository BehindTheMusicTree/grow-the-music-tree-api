from unittest import mock

from grow.genre_graph import service


def test_migrate_assignments_excludes_tracks_without_genre():
    with mock.patch.object(service, "_publish_legacy_assignments") as publish:
        service._migrate_assignments(mock.sentinel.dataset)
    population_sql = publish.call_args.args[1]
    assert "t.user_id IS NULL AND t.genre_id IS NOT NULL" in population_sql


def test_legacy_publication_passes_chunk_size_and_step_reporter():
    cursor = mock.MagicMock()
    cursor.fetchone.return_value = (False,)
    with (
        mock.patch.object(service, "register_evidence", return_value={"d": mock.Mock(pk=1)}),
        mock.patch.object(service, "publish_staged_attributions") as publish,
        mock.patch.object(service.connection, "cursor") as get_cursor,
    ):
        get_cursor.return_value.__enter__.return_value = cursor
        service._publish_legacy_assignments(mock.Mock(pk=1), "SELECT 1", [], {"decisionId": "d"})
    assert publish.call_args.kwargs["chunk_size"] == 1_000_000
    assert publish.call_args.kwargs["on_step"] is service.report_step
